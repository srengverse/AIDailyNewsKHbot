# ដោះស្រាយ Facebook Permission និង Render Deployment

## សេចក្តីសន្និដ្ឋានពី Log

Log បង្ហាញថា Gemini និង Supabase ដំណើរការជោគជ័យ។ តារាង `dharma_posts` ត្រូវបានបង្កើតរួច ព្រោះ API បានឆ្លើយ `200 OK` និងការរក្សាទុក content ថ្មីបានឆ្លើយ `201 Created`។ ការផុស Facebook បរាជ័យដោយ Meta error `(#200) pages_manage_posts are not available`។

បន្ទាត់ `No open ports detected` គឺជាបញ្ហាទីពីរ និងដាច់ដោយឡែក។ វាបង្ហាញថា service បច្ចុប្បន្នត្រូវបានបង្កើតជា **Render Web Service** ប៉ុន្តែ Start Command គឺ `python -m dharma_post_ai once --publish ...`។ Command នេះត្រូវរត់ម្តង ហើយបិទភ្លាមៗ ដូច្នេះវាមិនបើក HTTP port សម្រាប់ Web Service ឡើយ។

> សូម Pause service បច្ចុប្បន្នជាមុន ដើម្បីកុំឱ្យ Render restart ហើយបង្កើត failed records បន្ថែមក្នុង Supabase ពេលកំពុងកំណត់ Meta permission។

## A. កំណត់ Facebook Page Token ឡើងវិញ

### Permission ដែលត្រូវការ

| Permission | គោលបំណង |
|---|---|
| `pages_show_list` | អនុញ្ញាតឱ្យ App មើលបញ្ជី Pages ដែលអ្នកគ្រប់គ្រង។ |
| `pages_read_engagement` | អនុញ្ញាតឱ្យ App អានព័ត៌មានចាំបាច់ពី Page។ |
| `pages_manage_posts` | អនុញ្ញាតឱ្យ App បង្កើត កែ និងលុប Page posts។ |

`pages_manage_posts` គឺជាសិទ្ធិដែល Meta កំណត់សម្រាប់ការបង្កើត post នៅលើ Facebook Page [1]។

### ជំហានធ្វើនៅ Meta for Developers

1. ចូល [Meta for Developers](https://developers.facebook.com/apps/) ហើយជ្រើស Meta App ដែលប្រើបង្កើត token។
2. នៅ **Use cases** សូមបន្ថែម ឬកំណត់ use case សម្រាប់ការគ្រប់គ្រង Facebook Page។
3. នៅ **App Review → Permissions and Features** សូមស្វែងរក `pages_show_list`, `pages_read_engagement` និង `pages_manage_posts`។
4. សម្រាប់ការប្រើតែ Page ផ្ទាល់ខ្លួនក្នុង Development Mode សូមប្រាកដថា Facebook account ដែលបង្កើត token ត្រូវបានបន្ថែមជា **App Admin, Developer ឬ Tester** និងមាន Page task សិទ្ធិបង្កើត content។
5. សម្រាប់ការប្រើជាមួយអ្នកប្រើ ឬ Pages ខាងក្រៅ App roles សូមដាក់ស្នើ **Advanced Access / App Review** សម្រាប់ permissions ទាំងនេះតាមតម្រូវការរបស់ Meta។
6. បង្កើត **User Access Token** ថ្មីដោយស្នើ scopes ទាំងបីខាងលើ។
7. ប្រើ token នោះដើម្បីទាញយក **Page Access Token** សម្រាប់ Page ត្រឹមត្រូវ។ កុំដាក់ User Access Token ចូល `FACEBOOK_PAGE_ACCESS_TOKEN`។
8. នៅ [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/) សូមផ្ទៀងផ្ទាត់ថា token មាន `pages_manage_posts` និង Page ID ត្រូវនឹង `FACEBOOK_PAGE_ID`។
9. ដាក់ Page Access Token ថ្មីក្នុង Render Environment Variable `FACEBOOK_PAGE_ACCESS_TOKEN` ហើយ Save Changes។ កុំផ្ញើ ឬបញ្ចូល token នេះក្នុង chat, GitHub, ឬ source code។

## B. ជ្រើស Render Service តែមួយ

### ជម្រើស 1៖ 24/7 Web Service — សម្រាប់អ្វីដែលអ្នកកំពុងត្រូវការ

ប្រសិនបើបូតត្រូវនៅ online 24/7 សូមបង្កើត/កែ **Web Service** ដោយប្រើ [`render-web.yaml`](render-web.yaml) ឬកំណត់ដោយដៃដូចនេះ៖

| Setting | តម្លៃត្រឹមត្រូវ |
|---|---|
| Service type | Web Service |
| Build Command | `pip install .` |
| Start Command | `python -m dharma_post_ai serve` |
| Health Check Path | `/health` |
| `TIMEZONE` | `Asia/Phnom_Penh` |
| `POST_TIME` | `07:00` |
| `AUTO_PUBLISH` | `true` |
| `REQUIRE_APPROVAL` | `false` |
| `MAX_DAILY_POSTS` | `1` |

**កុំប្រើ** `python -m dharma_post_ai once --publish ...` ជា Start Command របស់ Web Service។ `serve` គឺជាកម្មវិធីដែលបើក scheduler និង HTTP `/health` ចំណែក `once` គឺ command សម្រាប់ Cron Job ដែលបញ្ចប់ការងាររួចបិទ។

### ជម្រើស 2៖ Cron Job — សម្រាប់រត់តែមួយដងតាមម៉ោង

ប្រសិនបើអ្នកចង់ឱ្យ Render បើក bot តែពេលត្រូវផុស សូមបង្កើត **Cron Job** ដោយប្រើ [`render.yaml`](render.yaml)។ រក្សា Start Command នេះ៖

```bash
python -m dharma_post_ai once --publish --topic 'សតិ និងសេចក្តីមេត្តា'
```

កំណត់ schedule ជា `0 0 * * *` ដែលស្មើ 07:00 ព្រឹកនៅកម្ពុជា ព្រោះ Render Cron គិតកាលវិភាគជា UTC [2]។

> កុំបើក Web Service Scheduler និង Cron Job នៅពេលតែមួយ។ សម្រាប់ Page មួយ ត្រូវមាន auto publisher មួយប៉ុណ្ណោះ។

## C. លំដាប់សាកល្បងដែលមិនផុសស្ទួន

1. Pause Web Service/ Cron Job ចាស់ដែលកំណត់ខុស។
2. បង្កើត Page Access Token ថ្មីដែលមាន `pages_manage_posts`។
3. ជ្រើស Mode មួយ៖ Web Service 24/7 **ឬ** Cron Job។
4. កំណត់ `MAX_DAILY_POSTS=1`។
5. Deploy កំណែថ្មី។
6. ប្រសិនបើជ្រើស Web Service សូមចូល `/health` ហើយមើល `scheduler_running: true`។
7. កុំចុច Trigger Run ឬ Redeploy ដើម្បី “សាកល្បង” នៅពេល Start Command មាន `--publish` ព្រោះវាអាចផុសពិតប្រាកដ។ សម្រាប់ការសាកល្បងជាមុន ត្រូវរត់ command `python -m dharma_post_ai once` ដោយគ្មាន `--publish` នៅ local environment ឬកែ setting ឱ្យ review mode ជាមុន។

## References

[1] [Meta Permissions Reference](https://developers.facebook.com/docs/permissions/)

[2] [Render Cron Jobs Documentation](https://render.com/docs/cronjobs)
