from abc import ABC, abstractmethod


class BaseProvider(ABC):

    @abstractmethod
    def send_email(
        self,
        to_email,
        subject,
        html_body,
        text_body=None,
        attachments=None,
    ):
        """
        Sends an email using the provider.
        """
        pass