from providers.smtp_provider import SMTPProvider
from providers.office365_provider import Office365Provider

# Future providers
try:
    from providers.sendgrid_provider import SendGridProvider
except Exception:
    SendGridProvider = None

try:
    from providers.ses_provider import SESProvider
except Exception:
    SESProvider = None

try:
    from providers.mailgun_provider import MailgunProvider
except Exception:
    MailgunProvider = None

try:
    from providers.smtp2go_provider import SMTP2GOProvider
except Exception:
    SMTP2GOProvider = None

try:
    from providers.sparkpost_provider import SparkPostProvider
except Exception:
    SparkPostProvider = None

try:
    from providers.mailersend_provider import MailerSendProvider
except Exception:
    MailerSendProvider = None

try:
    from providers.microsoft_graph_provider import MicrosoftGraphProvider
except Exception:
    MicrosoftGraphProvider = None


PROVIDERS = {
    "smtp": SMTPProvider,
    "office365": Office365Provider,
}


if SendGridProvider:
    PROVIDERS["sendgrid"] = SendGridProvider

if SESProvider:
    PROVIDERS["ses"] = SESProvider

if MailgunProvider:
    PROVIDERS["mailgun"] = MailgunProvider

if SMTP2GOProvider:
    PROVIDERS["smtp2go"] = SMTP2GOProvider

if SparkPostProvider:
    PROVIDERS["sparkpost"] = SparkPostProvider

if MailerSendProvider:
    PROVIDERS["mailersend"] = MailerSendProvider

if MicrosoftGraphProvider:
    PROVIDERS["graph"] = MicrosoftGraphProvider