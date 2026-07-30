from providers.smtp_provider import SMTPProvider
from providers.office365_provider import Office365Provider
from providers.graph_provider import GraphProvider
from providers.sendgrid_provider import SendGridProvider



class EmailSender:


    def __init__(
        self,
        provider_name,
        config
    ):

        self.provider_name = provider_name.lower()
        self.config = config

        self.provider = self.load_provider()



    def load_provider(self):


        if self.provider_name == "smtp":

            return SMTPProvider(

                host=self.config["host"],

                port=self.config["port"],

                username=self.config["username"],

                password=self.config["password"],

                sender_name=self.config["sender_name"],

                sender_email=self.config["sender_email"]

            )



        elif self.provider_name == "office365":

            return Office365Provider(

                username=self.config["username"],

                password=self.config["password"],

                sender_name=self.config["sender_name"],

                sender_email=self.config["sender_email"]

            )



        elif self.provider_name == "graph":

            return GraphProvider(

                tenant_id=self.config["tenant_id"],

                client_id=self.config["client_id"],

                client_secret=self.config["client_secret"],

                sender_email=self.config["sender_email"]

            )



        elif self.provider_name == "sendgrid":

            return SendGridProvider(

                api_key=self.config["api_key"],

                sender_name=self.config["sender_name"],

                sender_email=self.config["sender_email"]

            )



        else:

            raise ValueError(
                f"Unknown provider: {self.provider_name}"
            )




    def send(
        self,
        to_email,
        subject,
        html_body,
        text_body=None,
        attachments=None
    ):


        return self.provider.send_email(

            to_email=to_email,

            subject=subject,

            html_body=html_body,

            text_body=text_body,

            attachments=attachments

        )