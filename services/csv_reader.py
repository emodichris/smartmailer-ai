import pandas as pd


class CSVReader:
    @staticmethod
    def read_emails(file_path):
        """
        Reads CSV files and extracts email addresses.
        Supports:
        - CSV files with email columns
        - CSV files containing only email addresses
        """

        df = pd.read_csv(file_path, header=None)

        emails = []

        for column in df.columns:
            for value in df[column].dropna().astype(str):
                if "@" in value:
                    emails.append(value.strip())

        return list(set(emails))