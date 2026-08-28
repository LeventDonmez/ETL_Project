import os
import pandas as pd


class RawIngestion:
    """
    Ingestion: ERP ham CSV dosyalarını bulur ve hafızaya yükler.
    """

    def __init__(self, search_root=None):
        self.search_root = search_root if search_root else os.path.expanduser("~")
        self.target_files = ["CUST_AZ12", "LOC_A101", "PX_CAT_G1V2"]
        self.raw_data = {}

    def _find_file(self, target_name: str) -> str:
        """Dosyayı search_root altında arar, tam yolunu döner."""
        print(f"🔎 '{target_name}' dosyası aranıyor...")

        for root, _dirs, files in os.walk(self.search_root):
            for file in files:
                if file == target_name or file == f"{target_name}.csv":
                    full_path = os.path.join(root, file)
                    print(f"   └─► Bulundu: {full_path}")
                    return full_path

        raise FileNotFoundError(
            f"❌ HATA: '{target_name}' dosyası '{self.search_root}' altında bulunamadı!"
        )

    def load_raw_data(self) -> dict:
        """Üç hedef CSV'yi okuyup {dosya_adı: DataFrame} sözlüğü döner."""
        print("\n📥 [1/4] INGESTION Aşaması Başladı...")

        for file_name in self.target_files:
            file_path = self._find_file(file_name)
            self.raw_data[file_name] = pd.read_csv(file_path)

        print("   └─► Tüm ham veriler hafızaya yüklendi.")
        return self.raw_data



