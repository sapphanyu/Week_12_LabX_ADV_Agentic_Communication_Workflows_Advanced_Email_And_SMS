# src/communication_agent.py
import os
import json
import datetime
from utils import setup_logging, log_audit_entry, ensure_directory_exists, get_env_variable
from email_tasks import EmailTasks
from sms_tasks import SMSTasks
from template_renderer import TemplateRenderer

logger = setup_logging(__name__)

class CommunicationAgent:
    def __init__(self, config, base_dir):
        self.config = config
        self.audit_log = []
        self.context = {}
        self.start_time = datetime.datetime.now()
        self.base_dir = base_dir

        try:
            sender_email = get_env_variable("SENDER_EMAIL")
            sender_app_password = get_env_variable("SENDER_APP_PASSWORD")
            smtp_server = get_env_variable("SMTP_SERVER")
            smtp_port = int(get_env_variable("SMTP_PORT"))
            imap_server = get_env_variable("IMAP_SERVER")

            self.email_tasks = EmailTasks(smtp_server, smtp_port, imap_server, sender_email, sender_app_password)
            self.sms_tasks = SMSTasks(self.email_tasks)
            self.template_renderer = TemplateRenderer()
            logger.info("CommunicationAgent initialized with task handlers.")
        except ValueError as e:
            logger.critical(f"Agent initialization failed: Missing environment variables. {e}")
            raise

    def _update_context(self, key, value):
        self.context[key] = value

    def _render_template(self, template_string):
        try:
            return self.template_renderer.render(template_string, self.context)
        except Exception as e:
            log_audit_entry(self.audit_log, "ERROR", f"Template rendering failed: {e}", "template_render")
            raise

    def _process_task(self, task):
        task_type = task.get("type")
        task_name = task.get("name", task_type)
        task_params = task.get("parameters", {})
        output_context_key = task.get("output_context_key")

        logger.info(f"Executing task: '{task_name}' (Type: {task_type})")
        log_audit_entry(self.audit_log, "INFO", f"Starting task '{task_name}'", task_type, task)

        try:
            success = False
            task_output_data = None

            if task_type == "send_email":
                recipients = {k: [self._render_template(r) for r in v] for k, v in task_params.get('recipients', {}).items()}
                subject = self._render_template(task_params.get("subject_template"))
                body = self._render_template(task_params.get("body_template"))

                attachments = [os.path.join(self.base_dir, self._render_template(att_path)) for att_path in task_params.get("attachments", [])]
                is_html = task_params.get("is_html", False)
                success = self.email_tasks.send_email(recipients, subject, body, attachments, is_html)
                if success: task_output_data = {"recipients": recipients, "subject": subject}

            elif task_type == "send_sms":
                phone_numbers = [self._render_template(p) for p in task_params.get("phone_numbers", [])]
                message = self._render_template(task_params.get("message_template"))
                carrier_name = task_params.get("carrier_name")
                success = self.sms_tasks.send_sms(phone_numbers, message, carrier_name)
                if success: task_output_data = {"phone_numbers": phone_numbers, "message": message}

            elif task_type == "process_inbox":
                mailbox = task_params.get("mailbox", "INBOX")
                search_criteria = task_params.get("search_criteria", {})
                rules = task_params.get("rules", [])
                download_dir = os.path.join(self.base_dir, task_params.get("download_attachments_base_dir", "data/incoming_attachments"))

                rendered_sender = self._render_template(search_criteria.get("from_sender", "")) if search_criteria.get("from_sender") else None
                rendered_subject = self._render_template(search_criteria.get("subject_contains", "")) if search_criteria.get("subject_contains") else None

                uids = self.email_tasks.search_emails(mailbox=mailbox, criteria=search_criteria.get("status", "UNSEEN"), from_sender=rendered_sender, subject_contains=rendered_subject)

                if uids:
                    for uid in uids:
                        email_info = self.email_tasks.fetch_email_content(uid=uid, mark_as_read=True, download_attachments_dir=download_dir)
                        if email_info:
                            for rule in rules:
                                if_cond = rule.get("if", {})
                                then_act = rule.get("then", {})
                                condition_met = True

                                if "subject_contains" in if_cond and if_cond["subject_contains"] not in email_info['subject']: condition_met = False
                                if "body_contains" in if_cond and if_cond["body_contains"] not in email_info['text_body']: condition_met = False
                                if "has_attachments" in if_cond and if_cond["has_attachments"] != email_info['has_attachments']: condition_met = False

                                if condition_met:
                                    logger.info(f"Rule matched for email UID {email_info['uid']}.")
                                    if "send_sms_alert" in then_act and then_act["send_sms_alert"]:
                                        alert_msg = self.template_renderer.render(then_act.get("alert_message_template", "Urgent!"), {**self.context, **email_info})
                                        self.sms_tasks.send_sms([self._render_template(p) for p in then_act.get("alert_phone_numbers", [])], alert_msg, then_act.get("alert_carrier"))
                                    if "reply_with_template" in then_act:
                                        reply_body = self.template_renderer.render(then_act["reply_with_template"], {**self.context, **email_info})
                                        reply_subj = self.template_renderer.render(then_act.get("reply_subject_template", "Re: {subject}"), {**self.context, **email_info})
                                        self.email_tasks.send_email(recipients={'to': [email_info['sender']]}, subject=reply_subj, body=reply_body)
                    success = True
                else:
                    success = True
            else:
                logger.warning(f"Unsupported task type: {task_type}")
                return

            if success and task_output_data is not None and output_context_key:
                self._update_context(output_context_key, task_output_data)

            log_audit_entry(self.audit_log, "SUCCESS" if success else "ERROR", f"Task '{task_name}' {'completed' if success else 'failed'}.", task_type)
        except Exception as e:
            log_audit_entry(self.audit_log, "ERROR", f"An error occurred during task '{task_name}': {e}", task_type)
            logger.error(f"Error during task '{task_name}': {e}", exc_info=True)

    def _generate_audit_report(self, output_dir="reports"):
        ensure_directory_exists(output_dir)
        report_path = os.path.join(output_dir, f"audit_report_comm_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(self.audit_log, f, indent=4, ensure_ascii=False)
            logger.info(f"Audit report saved to: {report_path}")
        except Exception as e:
            logger.error(f"Failed to save audit report: {e}")

    def run(self):
        logger.info("Starting Communication Agent run...")
        # Inject dummy context data
        self._update_context("report_name", "DailySalesSummary")
        self._update_context("report_date", datetime.date.today().strftime("%Y-%m-%d"))
        self._update_context("sales_figure", 12345.67)
        self._update_context("total_customers", 500)

        for task in self.config.get("tasks", []):
            self._process_task(task)

        self._generate_audit_report(os.path.join(self.base_dir, 'reports'))
        logger.info("Communication Agent finished.")
