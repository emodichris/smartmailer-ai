class Deduplicator:
    @staticmethod
    def remove(emails):
        unique = []
        seen = set()

        for email in emails:
            email = email.strip().lower()

            if email not in seen:
                seen.add(email)
                unique.append(email)

        return unique