import os
from datetime import datetime
from typing import Optional, Tuple

import pandas as pd


class CuratedData:
    """
    Curation: Transformed veriden Dim tablolarını üretir ve CSV olarak kaydeder.
    """

    COUNTRY_LOOKUP = {
        "australia": ("Australia", "AU"),
        "united states": ("United States", "US"),
        "usa": ("United States", "US"),
        "us": ("United States", "US"),
        "united kingdom": ("United Kingdom", "GB"),
        "uk": ("United Kingdom", "GB"),
        "france": ("France", "FR"),
        "canada": ("Canada", "CA"),
        "germany": ("Germany", "DE"),
        "de": ("Germany", "DE"),
        "unknown": ("UNKNOWN", "UNK"),
    }

    def __init__(self, transformed_data: dict, output_dir: Optional[str] = None):
        self.merged_cust_df = transformed_data["merged_cust"]
        self.prod_df = transformed_data["prod"]
        self.loc_df = transformed_data["loc"]

        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.output_dir = output_dir or os.path.join(project_root, "output")
        os.makedirs(self.output_dir, exist_ok=True)

    def _resolve_country(self, raw_country) -> Tuple[str, str]:
        """Ham ülke değerini (CountryName, CountryCode) çiftine çevirir."""
        if pd.isna(raw_country):
            return ("UNKNOWN", "UNK")

        key = str(raw_country).strip().lower()
        if not key:
            return ("UNKNOWN", "UNK")

        return self.COUNTRY_LOOKUP.get(key, (str(raw_country).strip(), "UNK"))

    def _create_dim_customer(self, load_date: datetime) -> pd.DataFrame:
        """DimCustomer tablosunu oluşturur."""
        country_pairs = self.merged_cust_df["CNTRY"].map(self._resolve_country)

        return pd.DataFrame({
            "CustomerKey": range(1, len(self.merged_cust_df) + 1),
            "CustomerID": self.merged_cust_df["CID"],
            "BirthDate": self.merged_cust_df["BDATE"],
            "Age": self.merged_cust_df["Age"],
            "AgeGroup": self.merged_cust_df["AgeGroup"],
            "Gender": self.merged_cust_df["GEN_CLEAN"],
            "Country": country_pairs.map(lambda x: x[0]),
            "CountryCode": country_pairs.map(lambda x: x[1]),
            "ETLLoadDate": load_date,
        })

    def _create_dim_product_category(self, load_date: datetime) -> pd.DataFrame:
        """DimProductCategory tablosunu oluşturur."""
        return pd.DataFrame({
            "ProductCategoryKey": range(1, len(self.prod_df) + 1),
            "ProductCategoryID": self.prod_df["ID"],
            "Category": self.prod_df["CAT"],
            "SubCategory": self.prod_df["SUBCAT"],
            "MaintenanceFlag": self.prod_df["MAINTENANCE"].apply(
                lambda x: 1 if str(x).lower() in ["true", "1", "yes"] else 0
            ),
            "ETLLoadDate": load_date,
        })

    def _create_dim_country(self) -> pd.DataFrame:
        """DimCountry tablosunu benzersiz standart ülkelerden oluşturur."""
        country_pairs = self.loc_df["CNTRY"].map(self._resolve_country)
        dim_country = pd.DataFrame({
            "CountryName": country_pairs.map(lambda x: x[0]),
            "CountryCode": country_pairs.map(lambda x: x[1]),
        }).drop_duplicates().reset_index(drop=True)

        dim_country.insert(0, "CountryKey", range(1, len(dim_country) + 1))
        return dim_country

    def _save_csv(self, tables: dict) -> None:
        """Dim tablolarını output/ altına CSV olarak yazar."""
        for table_name, df in tables.items():
            path = os.path.join(self.output_dir, f"{table_name}.csv")
            df.to_csv(path, index=False)
        print(f"   └─► Dim CSV'ler kaydedildi: {self.output_dir}")

    def create_dimension_tables(self) -> dict:
        """Tüm Dim tablolarını üretir, kaydeder ve sözlük olarak döner."""
        print("\n🎯 [3/4] CURATION Aşaması Başladı...")
        load_date = datetime.now()

        tables = {
            "DimCustomer": self._create_dim_customer(load_date),
            "DimProductCategory": self._create_dim_product_category(load_date),
            "DimCountry": self._create_dim_country(),
        }
        self._save_csv(tables)
        return tables


