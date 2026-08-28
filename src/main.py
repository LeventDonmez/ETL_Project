import os
import shutil
import sys
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from data.raw import RawIngestion
from data.transformed import DataTransformation
from data.curated import CuratedData

FOLDER_MIME = "application/vnd.google-apps.folder"
ISTANBUL = ZoneInfo("Europe/Istanbul")


def _secrets_dir() -> str:
    """GitHub Actions secrets/ klasörü, yoksa yerel .gitignore/ klasörü."""
    env_dir = os.environ.get("ETL_SECRETS_DIR")
    if env_dir:
        return env_dir

    secrets_dir = os.path.join(project_root, "secrets")
    ignore_dir = os.path.join(project_root, ".gitignore")
    if os.path.isdir(secrets_dir):
        return secrets_dir
    return ignore_dir


class Main:
    """
    Drive'dan o günün raporlarını indirir, ETL uygular, Dim CSV'leri geri yükler.
    Zamanlamayı GitHub Actions cron'u yapar (her gün 09:00 Istanbul).
    """

    TARGET_TABLES = ("CUST_AZ12", "LOC_A101", "PX_CAT_G1V2")
    DRIVE_OUTPUT_FOLDER = "ETL_Output"

    def __init__(self, upload_to_drive: bool = True):
        self.upload_to_drive = upload_to_drive
        self.curated_output = None
        self.output_dir = None
        self.drive = None
        self.headless = (
            os.environ.get("GITHUB_ACTIONS") == "true"
            or os.environ.get("ETL_HEADLESS") == "1"
        )

        secrets_dir = _secrets_dir()
        self.secrets_path = os.path.join(secrets_dir, "client_secrets.json")
        self.credentials_path = os.path.join(secrets_dir, "credentials.json")
        self.input_dir = os.path.join(project_root, "input")

    def _authenticate_drive(self) -> None:
        print("🔑 Google Drive ile kimlik doğrulaması başlatılıyor...")

        if not os.path.exists(self.secrets_path):
            raise FileNotFoundError(
                f"client_secrets.json bulunamadı: {self.secrets_path}"
            )

        gauth = GoogleAuth()
        gauth.settings["get_refresh_token"] = True
        gauth.LoadClientConfigFile(self.secrets_path)

        if os.path.exists(self.credentials_path):
            gauth.LoadCredentialsFile(self.credentials_path)

        has_refresh_token = (
            gauth.credentials is not None
            and getattr(gauth.credentials, "refresh_token", None) is not None
        )

        if gauth.credentials is None or not has_refresh_token:
            if self.headless:
                raise RuntimeError(
                    "GitHub Actions tarayıcı açamaz. Repo Secrets'a "
                    "refresh_token içeren CREDENTIALS_JSON ekle."
                )
            print("   └─► Kalıcı yetki gerekiyor, tarayıcı açılıyor (tek seferlik)...")
            gauth.LocalWebserverAuth()
        elif gauth.access_token_expired:
            gauth.Refresh()
        else:
            gauth.Authorize()

        os.makedirs(os.path.dirname(self.credentials_path), exist_ok=True)
        gauth.SaveCredentialsFile(self.credentials_path)
        self.drive = GoogleDrive(gauth)
        print("✅ Kimlik doğrulama başarılı!")

    def _ensure_drive(self) -> None:
        if self.drive is None:
            self._authenticate_drive()

    @staticmethod
    def _date_tag(day: Optional[datetime] = None) -> str:
        """Dosya adında aranan gün_ay_yıl (Istanbul)."""
        when = day or datetime.now(ISTANBUL)
        if when.tzinfo is None:
            when = when.replace(tzinfo=ISTANBUL)
        return when.strftime("%d_%m_%Y")

    def _find_drive_file(self, table_name: str, date_tag: str):
        query = f"title contains '{date_tag}' and trashed=false"
        candidates = self.drive.ListFile({"q": query}).GetList()
        matches = [
            f for f in candidates
            if table_name.lower() in f["title"].lower()
            and f["mimeType"] != FOLDER_MIME
        ]
        if not matches:
            return None
        matches.sort(key=lambda f: f.get("modifiedDate", ""), reverse=True)
        return matches[0]

    def _get_or_create_folder(self, folder_name: str) -> str:
        query = (
            f"title = '{folder_name}' and mimeType = '{FOLDER_MIME}' "
            "and trashed = false"
        )
        existing = self.drive.ListFile({"q": query}).GetList()
        if existing:
            return existing[0]["id"]

        folder = self.drive.CreateFile(
            {"title": folder_name, "mimeType": FOLDER_MIME}
        )
        folder.Upload()
        print(f"   └─► Drive'da '{folder_name}' klasörü oluşturuldu.")
        return folder["id"]

    def run_download(self, day: Optional[datetime] = None) -> dict:
        date_tag = self._date_tag(day)
        print(f"\n📨 [1/4] Drive'dan '{date_tag}' tarihli raporlar indiriliyor...")
        self._ensure_drive()

        if os.path.isdir(self.input_dir):
            shutil.rmtree(self.input_dir)
        os.makedirs(self.input_dir, exist_ok=True)

        downloaded = {}
        missing = []
        for table_name in self.TARGET_TABLES:
            drive_file = self._find_drive_file(table_name, date_tag)
            if drive_file is None:
                missing.append(table_name)
                continue

            local_path = os.path.join(self.input_dir, f"{table_name}.csv")
            drive_file.GetContentFile(local_path)
            downloaded[table_name] = local_path
            print(f"   └─► {drive_file['title']} → input/{table_name}.csv")

        if missing:
            raise FileNotFoundError(
                f"Drive'da '{date_tag}' tarihli şu raporlar bulunamadı: "
                f"{', '.join(missing)}"
            )
        return downloaded

    def _upload_file(self, local_file_path: str, folder_id: Optional[str] = None) -> Optional[str]:
        self._ensure_drive()
        if not os.path.exists(local_file_path):
            print(f"❌ Hata: {local_file_path} bulunamadı!")
            return None

        file_name = os.path.basename(local_file_path)
        print(f"🚀 '{file_name}' Google Drive'a yükleniyor...")

        scope = f"'{folder_id}' in parents" if folder_id else "'root' in parents"
        query = f"title = '{file_name}' and {scope} and trashed = false"
        existing = self.drive.ListFile({"q": query}).GetList()

        if existing:
            drive_file = existing[0]
        else:
            metadata = {"title": file_name}
            if folder_id:
                metadata["parents"] = [{"id": folder_id}]
            drive_file = self.drive.CreateFile(metadata)

        drive_file.SetContentFile(local_file_path)
        drive_file.Upload()
        print(f"   └─► Yüklendi | File ID: {drive_file['id']}")
        return drive_file["id"]

    def run_load(self) -> dict:
        print(f"\n☁️  [4/4] '{self.DRIVE_OUTPUT_FOLDER}' klasörüne yükleniyor...")
        self._ensure_drive()

        if not self.curated_output or not self.output_dir:
            raise RuntimeError("Önce run_curate() çalıştırılmalı.")

        folder_id = self._get_or_create_folder(self.DRIVE_OUTPUT_FOLDER)
        uploaded = {}
        for table_name in self.curated_output.keys():
            local_path = os.path.join(self.output_dir, f"{table_name}.csv")
            file_id = self._upload_file(local_path, folder_id=folder_id)
            if file_id:
                uploaded[f"{table_name}.csv"] = file_id

        print(f"🎉 {len(uploaded)} curated CSV Google Drive'a yüklendi!")
        for name, file_id in uploaded.items():
            print(f"   • {name} → {file_id}")
        return uploaded

    def run_raw(self) -> dict:
        return RawIngestion(search_root=self.input_dir).load_raw_data()

    def run_transform(self, raw_output: dict) -> dict:
        return DataTransformation(raw_output).transform()

    def run_curate(self, transformed_output: dict) -> dict:
        curator = CuratedData(transformed_output)
        self.output_dir = curator.output_dir
        self.curated_output = curator.create_dimension_tables()
        return self.curated_output

    def run(self, day: Optional[datetime] = None) -> dict:
        start = datetime.now(ISTANBUL)
        print("==================================================")
        print("🚀 ETL PIPELINE BAŞLATILDI")
        print(f"⏰ Başlangıç: {start.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print("==================================================")

        try:
            self.run_download(day)
            raw_output = self.run_raw()
            transformed_output = self.run_transform(raw_output)
            curated_output = self.run_curate(transformed_output)

            if self.upload_to_drive:
                self.run_load()

            duration = (datetime.now(ISTANBUL) - start).total_seconds()
            print("\n==================================================")
            print("✅ ETL PIPELINE BAŞARIYLA TAMAMLANDI!")
            print(f"⏱️ Toplam Süre: {duration:.2f} saniye")
            for table_name, df in curated_output.items():
                print(f"   • {table_name}: {len(df)} satır")
            print("==================================================")
            return curated_output
        except Exception as e:
            print("\n==================================================")
            print("❌ ETL PIPELINE HATA İLE DURDURULDU!")
            print(f"🚨 Hata Detayı: {e}")
            print("==================================================")
            raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Günlük Drive ETL (GitHub Actions)")
    parser.add_argument(
        "--date",
        help="Rapor tarihi DD_MM_YYYY. Verilmezse Istanbul bugünü kullanılır.",
    )
    args = parser.parse_args()

    day = datetime.strptime(args.date, "%d_%m_%Y") if args.date else None
    Main(upload_to_drive=True).run(day=day)
