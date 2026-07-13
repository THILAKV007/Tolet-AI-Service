import requests
import json

API_KEY = "sk_jqwxr33z_ptghLWV33P15gNw4SUYG8f85"

url = "https://api.sarvam.ai/translate"

headers = {
    "Content-Type": "application/json",
    "api-subscription-key": API_KEY
}

tanglish_text = "ennaku 2BHK veedu KK Nagar la venum with 15k budget"

payload = {
    "input": tanglish_text,
    "source_language_code": "ta-IN",
    "target_language_code": "en-IN",
    "speaker_gender": "Male",
    "mode": "formal"
}


response = requests.post(
    url,
    headers=headers,
    data=json.dumps(payload)
)

if response.status_code == 200:
    result = response.json()
    print("Original :", tanglish_text)
    print("English  :", result.get("translated_text"))
else:
    print("Error :", response.status_code)
    print(response.text)


