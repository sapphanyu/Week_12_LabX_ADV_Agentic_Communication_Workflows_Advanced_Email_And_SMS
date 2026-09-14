# src/config_parser.py
import json
import os
from utils import setup_logging

logger = setup_logging(__name__)

class ConfigParser:
    def __init__(self, config_path):
        self.config_path = config_path
        self.config = {}

    def load_config(self):
        if not os.path.exists(self.config_path):
            logger.critical(f"Configuration file not found: {self.config_path}")
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            self._validate_config()
            logger.info(f"Configuration loaded successfully from {self.config_path}")
            return self.config
        except json.JSONDecodeError as e:
            logger.critical(f"Invalid JSON format in config file: {e}")
            raise ValueError(f"Invalid JSON format in config file: {e}")
        except Exception as e:
            logger.critical(f"An error occurred while loading config: {e}")
            raise Exception(f"An error occurred while loading config: {e}")

    def _validate_config(self):
        required_top_level_fields = ["tasks"]
        for field in required_top_level_fields:
            if field not in self.config:
                raise ValueError(f"Missing required field in config: '{field}'")

        if not isinstance(self.config["tasks"], list):
            raise ValueError("Config field 'tasks' must be a list.")

        for i, task in enumerate(self.config["tasks"]):
            if "type" not in task:
                raise ValueError(f"Task {i} is missing 'type' field.")
            if "name" not in task:
                raise ValueError(f"Task {i} (type: {task['type']}) is missing 'name' field.")

            if task["type"] == "send_email":
                if "parameters" not in task or not all(k in task["parameters"] for k in ["recipients", "subject_template", "body_template"]):
                    raise ValueError(f"Task {i} (send_email) requires 'recipients', 'subject_template', 'body_template' in parameters.")
                if not isinstance(task["parameters"]["recipients"], dict) or "to" not in task["parameters"]["recipients"]:
                    raise ValueError(f"Task {i} (send_email) 'recipients' parameter must be a dict with a 'to' list.")
            elif task["type"] == "send_sms":
                if "parameters" not in task or not all(k in task["parameters"] for k in ["phone_numbers", "message_template"]):
                    raise ValueError(f"Task {i} (send_sms) requires 'phone_numbers', 'message_template' in parameters.")
            elif task["type"] == "process_inbox":
                if "parameters" not in task or "search_criteria" not in task["parameters"]:
                    raise ValueError(f"Task {i} (process_inbox) requires 'search_criteria' in parameters.")

        logger.info("Configuration validated.")
