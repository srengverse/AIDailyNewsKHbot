import telebot
import os
from dotenv import load_dotenv

load_dotenv()
from groq import Groq

# កំណត់អញ្ញាត (Variables)
# នៅលើ Render អ្នកត្រូវបញ្ចូលឈ្មោះទាំងនេះក្នុងផ្នែក Environment Variables
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')

bot = telebot.TeleBot(BOT_TOKEN)
client = Groq(api_key=GROQ_API_KEY)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        
        # ហៅ AI ពី Groq ប្រើ Model Llama 3
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system", 
                    "content": "You are a helpful assistant. You must always reply in Khmer language."
                },
                {
                    "role": "user", 
                    "content": message.text
                }
            ],
            model="llama-3.3-70b-versatile", # Updated to use a supported model
        )
        
        ai_reply = chat_completion.choices[0].message.content
        bot.reply_to(message, ai_reply)
        
    except Exception as e:
        print(f"Error: {e}")
        bot.reply_to(message, "សូមទោស មានបញ្ហាក្នុងការភ្ជាប់ទៅកាន់ AI។")

if __name__ == "__main__":
    print("Bot is running...")
    bot.polling(none_stop=True)