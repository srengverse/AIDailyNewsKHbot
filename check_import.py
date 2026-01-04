import google.generativeai as genai
import os
from dotenv import load_dotenv

# Load key
load_dotenv()
api_key = os.getenv('GEMINI_API_KEY')

if not api_key:
    print("❌ រកមិនឃើញ API Key ទេ។ សូមពិនិត្យមើល file .env ឡើងវិញ។")
else:
    genai.configure(api_key=api_key)
    print(f"🔑 កំពុងប្រើ Key: ...{api_key[-5:]}")
    print("🔍 កំពុងសួរទៅ Google ថាមាន Model អ្វីខ្លះ?...\n")
    
    try:
        count = 0
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f"✅ ឈ្មោះ Model: {m.name}")
                count += 1
        
        if count == 0:
            print("⚠️ មិនមាន Model ណាប្រើបានទេ។ (អាចមកពី API Key មិនត្រឹមត្រូវ ឬនៅតំបន់ដែលគេបិទ)")
            
    except Exception as e:
        print(f"❌ Error: {e}")