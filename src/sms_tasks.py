# src/sms_tasks.py
from utils import setup_logging
from email_tasks import EmailTasks
from template_renderer import TemplateRenderer

logger = setup_logging(__name__)

class SMSTasks:
    def __init__(self, email_tasks_instance):
        if not isinstance(email_tasks_instance, EmailTasks):
            raise TypeError("SMSTasks requires an instance of EmailTasks.")
        self.email_tasks = email_tasks_instance
        self.template_renderer = TemplateRenderer()

        self.carrier_gateways = {
            "att": "@txt.att.net", "verizon": "@vtext.com", "tmobile": "@tmomail.net",
            "sprint": "@messaging.sprintpcs.com", "boost": "@sms.boostmobile.com"
        }
        logger.info("SMSTasks initialized.")

    def send_sms(self, phone_numbers, message, carrier_name=None):
        success_count = 0
        total_attempts = 0
        for phone_number in phone_numbers:
            total_attempts += 1
            sms_gateway_address = None
            if carrier_name and carrier_name.lower() in self.carrier_gateways:
                sms_gateway_address = f"{phone_number}{self.carrier_gateways[carrier_name.lower()]}"
            elif '@' in phone_number and '.' in phone_number:
                sms_gateway_address = phone_number
            else:
                logger.warning(f"No specific carrier provided for {phone_number}. Cannot send SMS.")
                continue

            if sms_gateway_address:
                logger.info(f"Attempting to send SMS to {phone_number} via gateway: {sms_gateway_address}")
                if self.email_tasks.send_email(recipients={'to': [sms_gateway_address]}, subject="", body=message):
                    success_count += 1

        return success_count == total_attempts if total_attempts > 0 else False
