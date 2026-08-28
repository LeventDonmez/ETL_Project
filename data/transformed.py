import re
from datetime import datetime

import pandas as pd


class DataTransformation:
    """
    Transformation: Ham veriyi temizler, zenginleştirir ve birleştirir.
    """

    def __init__(self, raw_data: dict):
        self.cust_df = raw_data["CUST_AZ12"].copy()
        self.loc_df = raw_data["LOC_A101"].copy()
        self.prod_df = raw_data["PX_CAT_G1V2"].copy()

    @staticmethod
    def _normalize_cid(cid) -> str:
        """CID formatlarını ortak sayısal anahtara çevirir (NASAW00011000 ↔ AW-00011000)."""
        value = str(cid).strip().upper()
        for prefix in ("NASAW", "NAS", "AW"):
            if value.startswith(prefix):
                value = value[len(prefix):]
                break
        return re.sub(r"[^0-9]", "", value)

    def _clean_gender(self) -> None:
        """GEN alanını Male/Female/Unknown standardına çevirir."""
        gender_map = {
            "M": "Male", "m": "Male", "Male": "Male",
            "F": "Female", "f": "Female", "Female": "Female",
        }
        self.cust_df["GEN_CLEAN"] = self.cust_df["GEN"].map(gender_map).fillna("Unknown")

    def _calculate_age(self) -> None:
        """BDATE'ten Age ve AgeGroup üretir."""
        self.cust_df["BDATE"] = pd.to_datetime(self.cust_df["BDATE"], errors="coerce")
        current_year = datetime.now().year
        self.cust_df["Age"] = current_year - self.cust_df["BDATE"].dt.year

        def assign_age_group(age):
            if pd.isna(age):
                return "Unknown"
            if age < 18:
                return "<18"
            if age <= 35:
                return "18-35"
            if age <= 50:
                return "36-50"
            return "50+"

        self.cust_df["AgeGroup"] = self.cust_df["Age"].apply(assign_age_group)

    def _merge_customer_location(self) -> pd.DataFrame:
        """Normalize CID ile müşteri ve lokasyonu left join eder."""
        self.cust_df["CID_KEY"] = self.cust_df["CID"].map(self._normalize_cid)
        self.loc_df["CID_KEY"] = self.loc_df["CID"].map(self._normalize_cid)

        loc_for_merge = self.loc_df[["CID_KEY", "CNTRY"]].drop_duplicates(subset=["CID_KEY"])
        merged = pd.merge(self.cust_df, loc_for_merge, on="CID_KEY", how="left")

        matched = merged["CNTRY"].notna().sum()
        print(f"   └─► CID eşleşmesi: {matched}/{len(merged)} müşteriye ülke atandı.")

        merged["CNTRY"] = merged["CNTRY"].fillna("UNKNOWN")
        return merged.drop(columns=["CID_KEY"])

    def transform(self) -> dict:
        """Tüm transform adımlarını çalıştırır; curated için sözlük döner."""
        print("\n⚙️ [2/4] TRANSFORM Aşaması Başladı...")

        self._clean_gender()
        self._calculate_age()
        merged_cust_df = self._merge_customer_location()

        print("   └─► Veri temizleme, zenginleştirme ve birleştirme tamamlandı.")
        return {
            "merged_cust": merged_cust_df,
            "prod": self.prod_df,
            "loc": self.loc_df.drop(columns=["CID_KEY"], errors="ignore"),
        }


