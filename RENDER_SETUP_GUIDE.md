# មគ្គុទ្ទេសក៍ Render៖ Auto Post ដោយមិនស្ទួន

គម្រោង **DharmaPostAI Bot** ផ្តល់ជម្រើស Render ពីរ។ ទាំងពីរនេះអាចផុសសារដោយស្វ័យប្រវត្តិបាន ប៉ុន្តែ **មិនត្រូវដាក់ឱ្យដំណើរការរួមគ្នា** ទេ។ ប្រសិនបើ Cron Job និង Web Service ប្រើ Facebook token និង Supabase database ដូចគ្នា វាអាចបង្កើត និងផុសសារដូចគ្នា ឬសារផ្សេងគ្នានៅថ្ងៃតែមួយ។

> **គោលការណ៍មួយគត់:** សម្រាប់ Facebook Page មួយ សូមមាន **តែ Automatic Publisher មួយ** ប៉ុណ្ណោះ។ ជ្រើសរើស Cron Job *ឬ* Web Service Scheduler។

## ១. ជ្រើសរើសរបៀបដំណើរការមុនដំឡើង

| ជម្រើស | លក្ខណៈដំណើរការ | សមស្របនៅពេល | មិនគួរប្រើរួមជាមួយ |
|---|---|---|---|
| **Render Cron Job** | Render ចាប់ផ្ដើមកម្មវិធីតាមម៉ោងកំណត់, បង្កើត និងផុសរួចបិទ។ | អ្នកចង់បាន post មួយដងក្នុងមួយថ្ងៃ ឬតាមកាលវិភាគថេរ។ | Web Service ដែលរត់ `python -m dharma_post_ai serve`។ |
| **Render Web Service** | Process នៅដំណើរការ 24/7, មាន internal scheduler និង endpoint `/health`។ | អ្នកចង់ឱ្យបូតនៅ online ជានិច្ច, ត្រូវការស្ថានភាព `/health`, ឬមានគម្រោងបន្ថែម admin API ពេលក្រោយ។ | Cron Job ដែលផុសសារទៅ Facebook Page ដូចគ្នា។ |

Render Cron Job ប្រើម៉ោង **UTC** សម្រាប់ cron expression។ ដូច្នេះ ម៉ោង `07:00` នៅកម្ពុជា (UTC+7) គឺ `00:00` UTC ឬ `0 0 * * *`។ Render ក៏ធានាថាមិនមាន Run ច្រើនជាងមួយកំពុងដំណើរការសម្រាប់ Cron Job តែមួយពេលដំណាលគ្នាផងដែរ [1]។

**សូមកំណត់ន័យ “auto post 24/7” របស់អ្នកឱ្យច្បាស់:** ប្រសិនបើមានន័យថា “បូតត្រូវនៅ online គ្រប់ពេល” សូមជ្រើស Web Service។ ប្រសិនបើមានន័យថា “ត្រូវផុសដោយស្វ័យប្រវត្តិមួយដងរាល់ថ្ងៃ” Cron Job គ្រប់គ្រាន់ និងមិនចាំបាច់បើក process 24/7 ទេ។

---

## ២. ជម្រើស A — Render Cron Job សម្រាប់ Post ប្រចាំថ្ងៃ

Repository មាន [`render.yaml`](render.yaml) ដែលបានកំណត់ជា Cron Job រួច។ វារត់នៅម៉ោង **07:00 Asia/Phnom_Penh** រៀងរាល់ថ្ងៃ។

### ជំហានកំណត់

1. ចូល [Render Dashboard](https://dashboard.render.com) ហើយជ្រើស **New → Cron Job** ឬបង្កើត Blueprint ពី repository នេះ។
2. ជ្រើស repository `srengverse/AIDailyNewsKHbot` និង branch `main`។
3. ប្រសិនបើបង្កើតដោយដៃ សូមប្រើការកំណត់ដូចតារាងខាងក្រោម។

| Field នៅ Render | តម្លៃត្រូវកំណត់ |
|---|---|
| Runtime | `Python` |
| Build Command | `pip install .` |
| Start Command | `python -m dharma_post_ai once --publish --topic 'សតិ និងសេចក្តីមេត្តា'` |
| Schedule | `0 0 * * *` |
| Time meaning | 00:00 UTC = 07:00 ព្រឹក កម្ពុជា |

4. នៅ Environment Variables បញ្ចូល secrets ទាំងនេះដោយ **Manual Secret**៖ `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `FACEBOOK_PAGE_ID`, និង `FACEBOOK_PAGE_ACCESS_TOKEN`។
5. បញ្ចូល non-secret values ដូចខាងក្រោម៖

| Key | Value |
|---|---|
| `GEMINI_MODEL` | `gemini-2.5-flash` |
| `FACEBOOK_GRAPH_API_VERSION` | `v26.0` |
| `TIMEZONE` | `Asia/Phnom_Penh` |
| `AUTO_PUBLISH` | `true` |
| `REQUIRE_APPROVAL` | `false` |
| `MAX_DAILY_POSTS` | `1` |
| `FONT_PATH` | `Battambang-Bold.ttf` |

6. Deploy ហើយពិនិត្យ logs រហូតឃើញ Gemini, Supabase និង Facebook success។ **កុំចុច `Trigger Run` ដើម្បីសាកល្បង** លុះត្រាតែអ្នកព្រមឱ្យវាផុស Facebook ពិតប្រាកដ។

### លក្ខខណ្ឌមិនឱ្យស្ទួននៅ Cron Mode

ក្នុង Mode នេះ សូមកុំបង្កើត Web Service ដែលប្រើ `python -m dharma_post_ai serve`។ ផ្អាក ឬលុប Web Service ចាស់ជាមុន។ `MAX_DAILY_POSTS=1` នៅ Supabase ជួយទប់ស្កាត់ post លើសកំណត់ក្នុងថ្ងៃតែមួយ ប៉ុន្តែវាជា **ការពារបម្រុង** មិនមែនជាមូលហេតុអនុញ្ញាតឱ្យដាក់ schedulers ពីរទេ។

---

## ៣. ជម្រើស B — Render Web Service សម្រាប់ Bot Online 24/7

ជម្រើសនេះប្រើ [`render-web.yaml`](render-web.yaml) ជាគំរូ។ វារត់ `python -m dharma_post_ai serve`, បើក scheduler នៅក្នុង Python process និងមាន endpoint `/health`។ Render ផ្ញើ HTTP GET health check ទៅ endpoint ដែលអ្នកកំណត់ ហើយចាត់ទុក 2xx/3xx ក្នុងរយៈពេល 5 វិនាទីថាសុខភាពល្អ [2]។

### ជំហានកំណត់

1. **ផ្អាក ឬលុប Cron Job ជាមុនសិន។** សូមបញ្ជាក់ថាវាមិនមាន Run កំពុងដំណើរការ។
2. នៅ Render Dashboard ជ្រើស **New → Web Service** និងភ្ជាប់ repository/branch `main`។
3. ប្រើការកំណត់ខាងក្រោម។

| Field នៅ Render | តម្លៃត្រូវកំណត់ |
|---|---|
| Runtime | `Python` |
| Build Command | `pip install .` |
| Start Command | `python -m dharma_post_ai serve` |
| Health Check Path | `/health` |
| Port | Render បញ្ចូល `PORT`; គម្រោងប្រើ `8080` ជា fallback |

4. បញ្ចូល secrets 5 ដដែល៖ `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `FACEBOOK_PAGE_ID`, និង `FACEBOOK_PAGE_ACCESS_TOKEN`។
5. បញ្ចូល environment values ដូចខាងក្រោម។

| Key | Value | ពន្យល់ |
|---|---|---|
| `TIMEZONE` | `Asia/Phnom_Penh` | ឱ្យ scheduler គិតម៉ោងកម្ពុជា។ |
| `POST_TIME` | `07:00` | ម៉ោងផុសប្រចាំថ្ងៃ។ |
| `AUTO_PUBLISH` | `true` | អនុញ្ញាតឱ្យ scheduler ផុសដោយស្វ័យប្រវត្តិ។ |
| `REQUIRE_APPROVAL` | `false` | បិទ review queue សម្រាប់ auto-post ដោយផ្ទាល់។ |
| `MAX_DAILY_POSTS` | `1` | ទប់ស្កាត់ការផុសលើសមួយក្នុងមួយថ្ងៃ។ |
| `FONT_PATH` | `Battambang-Bold.ttf` | ពុម្ពអក្សរខ្មែរសម្រាប់ Poster។ |
| `FACEBOOK_GRAPH_API_VERSION` | `v26.0` | Graph API version។ |

6. Deploy ហើយចូល `https://<your-service>.onrender.com/health`។ អ្នកគួរទទួលបាន JSON ដែលមាន `status: "ok"`, `scheduled_time: "07:00"` និង `scheduler_running: true`។

### លក្ខខណ្ឌមិនឱ្យស្ទួននៅ Web Service Mode

បន្ទាប់ពី Web Service មាន `/health` ជោគជ័យ សូមកុំមាន Cron Job ផ្សេងទៀតដែលហៅ `once --publish` ទៅ Page ដូចគ្នា។ កុំដាក់ `render.yaml` និង `render-web.yaml` ជា Blueprint services ក្នុងគណនី Render ដូចគ្នា។

---

## ៤. របៀបប្ដូរពី Cron Job ទៅ Web Service ដោយសុវត្ថិភាព

1. Pause/Delete Cron Job ចាស់នៅ Render Dashboard។
2. ពិនិត្យ Cron Job logs និងរង់ចាំឱ្យ Run ចុងក្រោយបញ្ចប់។
3. នៅ Supabase ពិនិត្យ `dharma_posts` ថាមិនមាន record `approved` ដែលអ្នកមិនចង់ផុសទេ។
4. បង្កើត Web Service តាមជំហានខាងលើ។
5. ពិនិត្យ `/health` និង logs ម្តង។
6. តាមដាន post ដំបូងនៅម៉ោងកំណត់។

ដំណើរការប្ដូរពី Web Service ទៅ Cron Job គឺបញ្ច្រាសវិញ៖ បិទ Web Service សិន → ពិនិត្យថា process បានឈប់ → បើក Cron Job តែមួយ។

---

## ៥. Checklist មុនបើក Auto Post ពិតប្រាកដ

| ការត្រួតពិនិត្យ | តម្លៃដែលត្រូវមាន |
|---|---|
| Active automatic publisher | Cron Job **មួយ** ឬ Web Service **មួយ** ប៉ុណ្ណោះ |
| `MAX_DAILY_POSTS` | `1` |
| `TIMEZONE` | `Asia/Phnom_Penh` |
| Cron schedule (បើប្រើ Cron) | `0 0 * * *` សម្រាប់ 07:00 កម្ពុជា |
| `POST_TIME` (បើប្រើ Web Service) | `07:00` |
| `AUTO_PUBLISH` | `true` |
| `REQUIRE_APPROVAL` | `false` សម្រាប់ auto-post ដោយផ្ទាល់ |
| `/health` (បើប្រើ Web Service) | ឆ្លើយតប `status: ok` |
| Supabase SQL migration | បានរត់ជោគជ័យ |
| Facebook token | មានសិទ្ធិផុស Photo ទៅ Page |

## References

[1] [Render Cron Jobs Documentation](https://render.com/docs/cronjobs)

[2] [Render Health Checks Documentation](https://render.com/docs/health-checks)
