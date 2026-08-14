# Telegram Shift Reminder Bot

Bot នេះប្រើ `python-telegram-bot`, `APScheduler` និង `python-dotenv` ដើម្បីផ្ញើសាររំលឹកវេនសម្អាតកុដិទៅ Telegram Group រៀងរាល់ថ្ងៃនៅម៉ោង 05:30 តាមម៉ោងកម្ពុជា។

## 1. បង្កើត Bot និងយក Token

ក្នុង Telegram ស្វែងរក `@BotFather`, ប្រើ `/newbot`, បង្កើតឈ្មោះ Bot ហើយចម្លង token។ កុំបង្ហោះ token ទៅ GitHub ឬផ្ញើក្នុង Group។

បន្ថែម Bot ទៅ Group ដែលត្រូវការផ្ញើសារ។ ប្រសិនបើ Bot មិនអាចផ្ញើសារបាន សូមពិនិត្យថា Bot មិនត្រូវបាន restrict ហើយមានសិទ្ធិ send messages។

## 2. ដំឡើង Python environment

```bash
cd telegram_shift_bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

លើ Windows ប្រើ៖

```powershell
venv\\Scripts\\activate
pip install -r requirements.txt
```

## 3. បង្កើតឯកសារ .env

```bash
cp .env.example .env
```

បើក `.env` ហើយដាក់៖

```env
BOT_TOKEN=token_ពី_BotFather
GROUP_CHAT_ID=-1001234567890
TIMEZONE=Asia/Phnom_Penh
REMINDER_HOUR=5
REMINDER_MINUTE=30
```

## 4. ស្វែងរក Group Chat ID

ដំណើរការ Bot ជាមុនដោយមិនទាន់ដាក់ `GROUP_CHAT_ID` ឬដាក់តម្លៃបណ្តោះអាសន្ន៖

```bash
python bot.py
```

បន្ទាប់មកបញ្ចូល Bot ទៅក្នុង Group ហើយវាយ៖

```text
/chatid
```

Bot នឹងឆ្លើយជាមួយលេខ Chat ID។ ចម្លងលេខនោះទៅ `.env` ជា `GROUP_CHAT_ID` ហើយ restart Bot។

## 5. Commands

| Command | មុខងារ |
|---|---|
| `/start` | បង្ហាញជំនួយ និង commands |
| `/today` | បង្ហាញសាររំលឹកសម្រាប់ថ្ងៃនេះ |
| `/week` | បង្ហាញតារាងវេន ៧ ថ្ងៃ |
| `/test` | ផ្ញើសារសាកល្បងទៅ chat បច្ចុប្បន្ន |
| `/chatid` | បង្ហាញ Chat ID របស់ chat បច្ចុប្បន្ន |

## 6. ដំណើរការ

```bash
python bot.py
```

Terminal ត្រូវនៅដំណើរការ ដើម្បីឲ្យ Bot ផ្ញើសារបាន។ សម្រាប់ការប្រើប្រាស់ 24/7 គួរដាក់ Bot លើ VPS ឬ cloud server ដែលមិនបិទ។

## 7. កែឈ្មោះអ្នកមានវេន

កែ `WEEKLY_SHIFTS` នៅក្នុង `bot.py`។ លេខថ្ងៃគឺ៖ ចន្ទ `0`, អង្គារ `1`, ពុធ `2`, ព្រហស្បតិ៍ `3`, សុក្រ `4`, សៅរ៍ `5`, អាទិត្យ `6`។

## 8. សាកល្បង syntax

```bash
python3 -m py_compile bot.py
```

ប្រសិនបើគ្មានសារ error មានន័យថា syntax ត្រឹមត្រូវ។
