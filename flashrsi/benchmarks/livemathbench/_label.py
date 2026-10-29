# ruff: noqa
# fmt: off
# Extracted unchanged from OpenCompass; see upstream.json and LICENSE-APACHE.
import re


def extract_judge_label(text):
    if isinstance(text, str):
        match = re.findall(r'\\boxed{(.+?)}', text)
        if match:
            return match[-1]

    return None
