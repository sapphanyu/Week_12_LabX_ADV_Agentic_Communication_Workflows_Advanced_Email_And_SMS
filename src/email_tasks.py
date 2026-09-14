# src/email_tasks.py
import smtplib
import imaplib
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.header import decode_header
import os
from utils import setup_logging, ensure_directory_exists
from template_renderer import TemplateRenderer

logger = setup_logging(__name__)

class EmailTasks:
    def __init__(self, smtp_server, smtp_port, imap_server, sender_email, sender_password):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.imap_server = imap_server
        self.sender_email = sender_email
        self.sender_password = sender_password
        self._smtp_server = None
        self._imap_mail = None
        self.template_renderer = TemplateRenderer()
        logger.info(f"EmailTasks initialized for {sender_email}.")

    def _connect_smtp(self):
        if self._smtp_server: return True
        try:
            self._smtp_server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            self._smtp_server.starttls()
            self._smtp_server.login(self.sender_email, self.sender_password)
            logger.info("Successfully connected and logged into SMTP server.")
            return True
        except Exception as e:
            logger.error(f"SMTP connection/login failed: {e}")
            self._smtp_server = None
            return False

    def _disconnect_smtp(self):
        if self._smtp_server:
            try: self._smtp_server.quit()
            except: pass
            finally: self._smtp_server = None

    def send_email(self, recipients, subject, body, attachments=None, is_html=False):
        if not self._connect_smtp(): return False

        msg = MIMEMultipart()
        msg['From'] = self.sender_email
        msg['Subject'] = subject

        to_recipients = recipients.get('to', [])
        cc_recipients = recipients.get('cc', [])
        bcc_recipients = recipients.get('bcc', [])

        msg['To'] = ", ".join(to_recipients)
        if cc_recipients: msg['Cc'] = ", ".join(cc_recipients)

        msg.attach(MIMEText(body, 'html' if is_html else 'plain'))

        if attachments:
            for attachment_path in attachments:
                if not os.path.exists(attachment_path):
                    logger.warning(f"Attachment file not found: {attachment_path}. Skipping.")
                    continue
                try:
                    with open(attachment_path, "rb") as f:
                        part = MIMEApplication(f.read(), Name=os.path.basename(attachment_path))
                    part['Content-Disposition'] = f'attachment; filename="{os.path.basename(attachment_path)}"'
                    msg.attach(part)
                except Exception as e:
                    logger.error(f"Error attaching file {attachment_path}: {e}")

        all_recipients = to_recipients + cc_recipients + bcc_recipients
        if not all_recipients:
            logger.error("No recipients specified for email.")
            self._disconnect_smtp()
            return False

        try:
            self._smtp_server.send_message(msg, from_addr=self.sender_email, to_addrs=all_recipients)
            logger.info(f"Email sent successfully to {', '.join(to_recipients)}. Subject: '{subject}'.")
            return True
        except Exception as e:
            logger.error(f"Failed to send email. Error: {e}")
            return False
        finally:
            self._disconnect_smtp()

    def _connect_imap(self):
        if self._imap_mail: return True
        try:
            self._imap_mail = imaplib.IMAP4_SSL(self.imap_server)
            self._imap_mail.login(self.sender_email, self.sender_password)
            logger.info("Successfully connected and logged into IMAP server.")
            return True
        except Exception as e:
            logger.error(f"IMAP connection/login failed: {e}")
            self._imap_mail = None
            return False

    def _disconnect_imap(self):
        if self._imap_mail:
            try: self._imap_mail.logout()
            except: pass
            finally: self._imap_mail = None

    def search_emails(self, mailbox='INBOX', criteria='UNSEEN', from_sender=None, subject_contains=None):
        if not self._connect_imap(): return []
        try:
            self._imap_mail.select(mailbox)
            search_query = [criteria]
            if from_sender: search_query.extend(['FROM', from_sender])
            if subject_contains: search_query.extend(['SUBJECT', subject_contains])

            status, email_ids = self._imap_mail.search(None, *search_query)
            if status != 'OK': return []

            uids = email_ids[0].split()
            logger.info(f"Found {len(uids)} emails matching criteria in '{mailbox}'.")
            return uids
        except Exception as e:
            logger.error(f"Error searching emails: {e}")
            return []
        finally:
            self._disconnect_imap()

    def fetch_email_content(self, uid, mark_as_read=True, download_attachments_dir=None):
        if not self._connect_imap(): return None
        try:
            self._imap_mail.select('INBOX')
            status, msg_data = self._imap_mail.fetch(uid, '(RFC822)')
            if status != 'OK': return None

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            sender = self._decode_header_part(msg['From'])
            subject = self._decode_header_part(msg['Subject'])

            email_text_body = ""
            attachments_meta = []

            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                filename = part.get_filename()

                if "attachment" in content_disposition or (filename and part.get_content_maintype() != 'multipart'):
                    if filename and download_attachments_dir:
                        ensure_directory_exists(download_attachments_dir)
                        filepath = os.path.join(download_attachments_dir, filename)
                        try:
                            with open(filepath, "wb") as f:
                                f.write(part.get_payload(decode=True))
                            attachments_meta.append({'filename': filename, 'filepath': filepath})
                            logger.info(f"Downloaded attachment: {filepath}")
                        except Exception as e:
                            logger.error(f"Error downloading attachment {filename}: {e}")
                elif "text/plain" in content_type and "attachment" not in content_disposition:
                    try:
                        email_text_body += part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
                    except: pass

            if mark_as_read:
                self._imap_mail.store(uid, '+FLAGS', '\\Seen')

            return {
                "uid": uid.decode('utf-8'),
                "sender": sender,
                "subject": subject,
                "text_body": email_text_body,
                "has_attachments": bool(attachments_meta),
                "attachments_meta": attachments_meta
            }
        except Exception as e:
            logger.error(f"Error fetching/parsing email UID {uid}: {e}")
            return None
        finally:
            self._disconnect_imap()

    def _decode_header_part(self, header_value):
        if header_value is None: return ""
        decoded_parts = decode_header(header_value)
        decoded_string = ""
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                try: decoded_string += part.decode(charset if charset else 'utf-8')
                except: decoded_string += part.decode('latin-1', errors='replace')
            else:
                decoded_string += part
        return decoded_string.strip()
