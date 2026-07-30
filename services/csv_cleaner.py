import csv


class CSVCleaner:

    @staticmethod
    def clean_email_list(results):
        """
        Keeps valid emails, removes duplicates,
        removes empty values, and normalizes formatting.
        """

        clean_emails = set()

        for item in results:

            if item["valid"]:

                email = item["email"].strip().lower()

                # Ignore empty emails
                if email:
                    clean_emails.add(email)

        return sorted(list(clean_emails))


    @staticmethod
    def save_clean_csv(emails, filename="cleaned_emails.csv"):
        """
        Saves cleaned emails into a new CSV file.
        """

        with open(filename, "w", newline="", encoding="utf-8") as file:

            writer = csv.writer(file)

            writer.writerow(["email"])

            for email in emails:
                writer.writerow([email])

        return filename