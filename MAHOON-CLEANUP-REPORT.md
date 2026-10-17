# گزارش پاک‌سازی و تجمیع ماهون در ویندوز

## نتیجه

**PORTABILITY: PASS** — یک workspace مستقل و قابل‌انتقال آماده است.

**CLEANUP: PARTIAL_WITH_PROTECTED_EXCEPTIONS_AND_POLICY_BLOCKED_TEST_COPY** — پاک‌سازی واقعی انجام شد؛ همهٔ فایل‌های مرتبط از رایانه حذف نشده‌اند. فایل‌های مبهم/حساس، workspace فعال و یک کپی آزمایشی که حذفش توسط کنترل خودکار رد شد حفظ شده‌اند. این گزارش ادعای پاک‌سازی صددرصد یا حذف همهٔ نسخه‌های محلی ندارد.

پوشهٔ مرجع توسعه: **`C:\Users\mehdi karani\MAHOON`**. از این پس توسعه فقط در همین پوشه انجام شود. Git آن یک دایرکتوری واقعی `.git` با objectهای مستقل است؛ به worktree یا Git بیرون پوشه وابسته نیست.

زمان اندازه‌گیری: `2026-10-16T19:41:08.468938+00:00`. مقادیر GB ده‌دهی‌اند: 1GB=1,000,000,000 bytes.

## فضای دیسک و آمار واقعی

| مورد | مقدار |
|---|---:|
| inventory اولیهٔ نامزدها، شامل موارد نیازمند بررسی | 40.349 GB، 326 مسیر |
| footprint نهاییِ ثبت‌شده، با داده‌های محافظت‌شده و فایل‌های همین مأموریت | حدود 6.608 GB |
| بستهٔ نهایی MAHOON با رسانه‌ها و اسناد اصلی حفظ‌شده | حدود 0.620 GB |
| فایل‌های موقت/تکراری حذف‌شده با manifest دقیق | **371,337 فایل، 34.727 GB منطقی** |
| worktreeهای منسوخ حذف‌شده با Git | **28**، همراه حفظ 31 HEAD تاریخی |
| داده‌های legacy منتقل‌شده به بخش محافظت‌شده | 6,183 فایل، 1.040 GB؛ انتقال است، آزادسازی فضا نیست |
| داده‌های بیرون بسته که محافظه‌کارانه باقی مانده‌اند | 109,957 فایل در 302 مسیر، 5.324 GB منطقی |
| فایل‌ها و state باقی‌ماندهٔ همین مأموریت در Temp | 0.663 GB، شامل کپی آزمایشی مسدودشده |

inventory نامزدها براساس مسیر، نام، Git remote، worktree، metadata و بررسی محتوای مرتبط تهیه شد؛ همهٔ name matchها مالکیت قطعی MAHOON نیستند. پکیج سالن آرایشگاه با نام مشابه در E نامرتبط تشخیص داده شد و حذف نشد. اندازه‌های footprint، مجموع منطقی فایل‌ها هستند؛ فایل‌های hard link شده ممکن است چند نام داشته باشند. در inventory اولیه 29,954 نام فایل با چند لینک شناسایی شد. بنابراین 34.727GB حذف منطقی را به‌عنوان همان مقدار فضای واقعی آزادشده گزارش نمی‌کنیم. شمار بالا فایل‌های ثبت‌شده در چهار batch را پوشش می‌دهد؛ حذف source checkoutها با Git جداگانه ثبت شده و برای بزرگ‌تر کردن عدد به آن اضافه نشده است.

| درایو | فضای آزاد قبل | فضای آزاد در مشاهدهٔ نهایی | تغییر خالص مشاهده‌شده |
|---|---:|---:|---:|
| C | 178.215 GB | 205.603 GB | **+27.388 GB** |
| E | 291.722 GB | 291.496 GB | -0.226 GB |

**افزایش مشاهده‌شدهٔ فضای آزاد C حدود 27.4GB است.** E هم‌زمان فعالیت نوشتن دیگری داشته است؛ کاهش فضای آزاد آن به‌عنوان آزادسازی ماهون یا خرابی ناشی از cleanup تفسیر نمی‌شود. این‌ها مشاهدات واقعی volume هستند، نه انتساب انحصاری تک‌تک بایت‌ها به این مأموریت؛ فعالیت هم‌زمان ویندوز و برنامه‌های دیگر وجود داشته است. جابه‌جایی، آرشیو جدید، قرنطینه و Recycle Bin به‌عنوان فضای بازیابی‌شده شمرده نشده‌اند. حذف‌های موفق از قرنطینهٔ تأییدشده مستقیماً انجام شد؛ هیچ تخلیهٔ عمومی Recycle Bin صورت نگرفت.

## چه چیزی انجام شد

- دیسک‌های محلی C و E، Desktop/Documents/Downloads، مسیرهای توسعه، cloneها، worktreeهای Codex و Tempهای مرتبط بررسی شدند. مسیرهای سیستمی و نصب برنامه‌ها، محتوای خصوصی نامرتبط، credential store و state مشترک Codex دستکاری نشدند. reparse pointها دنبال نشدند؛ 3 مورد و 4 خطای دسترسی در discovery ثبت شده‌اند. مجوز ویندوز دور زده نشد و administrator درخواست نشد.
- پوشهٔ قدیمی `MAHOON` یک worktree detached وابسته به Git بیرونی بود. ابتدا با Git جابه‌جا شد؛ تغییرات و داده‌های ضروری آن حفظ شد و سپس checkout قدیمی با ابزار رسمی Git حذف شد. یک clone مستقل بدون hard link/alternates، با origin رسمی ساخته شد؛ 31 HEAD به شاخه‌های محلی `archive/local-worktree-*` منتقل شدند. این شاخه‌ها روی GitHub push نمی‌شوند.
- 2,683 فایل/patch تاریخی (0.032 GB غیر‌فشرده) با منشأ commit و SHA256 در `local-archive/historical-unique-work.zip` حفظ شدند. patchها خودکار اعمال نشدند. محتوای مشکوکِ credential به بسته منتقل نشد؛ تطبیق الگوهای توکن و assignmentهای حساسِ آرشیو نیز صفر مورد گزارش کرد. این بررسی جای مجوز export credential نیست؛ credentialهای محلی اصلاً انتخاب نشدند.
- **631 رسانهٔ تاریخی یکتا**، 0.578 GB، در یک ZIP بدون نسخه‌های تکراری حفظ و SHA256 تک‌تک فایل‌ها بررسی شد. manifestهای دقیق، نگاشت مسیر قبلی به digest را نگه می‌دارند. آرشیو برای منابع تاریخیِ احتمالاً غیرقابل‌بازسازی است؛ dependency اجرایی build نیست.
- **9 فایل اصلی PSD/PNG/JPG** از منابع طراحی، با نام و بایت اصلی و SHA256 به `local-archive/brand-originals` منتقل شدند. نسخهٔ سایت، لوگو و فونت‌های موجود در سورس تغییر نکردند. فقط نسخهٔ اضافی مبدأ پس از تطبیق و قرنطینه حذف شد؛ انتقال این فایل‌ها آزادسازی خالص کل دیسک‌ها محسوب نشده است.
- node_modulesهای cloneهای قدیمی، cacheهای compiler/Python، buildهای static و ZIPهای build منسوخ و صفحات تولیدشده حذف شدند. JSONهای شواهد و logهای مبهم در پاک‌سازی صفحات/رسانه دست‌نخورده ماندند. cacheهای داخل profileهای آزمون مرورگر پاک شدند؛ cookie، profile و هویت مرورگر حذف یا کپی نشد.
- شش launcher قدیمیِ rollback/restore در Downloads به متن غیرفعال داخل ZIP تاریخی تبدیل و نسخه‌های اجرایی زائد حذف شدند. هیچ launcher قدیمی اجرا نشد.
- قرنطینه‌ها قبل از purge از نظر مسیر، نبود reparse، تعداد، اندازه و metadata بررسی شدند؛ برای رسانه‌ها SHA256 نیز دوباره بررسی شد. دادهٔ تغییرکرده یا خارج از allowlist حذف نشد. رد اولیهٔ چند مسیر Temp با dry run محدود جدید و allowlist دقیق رفع شد؛ mutation موفق تکرار نشد.
- وابستگی‌های بازسازی‌شدنی و clone آزمایشیِ ایجادشده برای آزمون انتقال نیز پس از موفقیت حذف شدند. **استثنا**: یک کپی پایانی آرشیو توسط کنترل خودکار حذف ابزار مسدود شد و حفظ شده است.

## موارد باقی‌مانده و علت

| مسیر/گروه | علت حفظ |
|---|---|
| `C:\Users\mehdi karani\m11e-r86b-runner-clean\tg-cms` | cwd گفت‌وگوی فعال و داده‌های تشخیصی/منشأ قدیمی؛ workspace فعال حذف نمی‌شود |
| `C:\Users\mehdi karani\.codex\worktrees\mahoon-finalize\tg-cms` | worktree متصل به همین گفت‌وگوی فعال و graph محلی |
| `C:\User\Users\tg-cms` | Git مشترک موردنیاز دو مسیر فعال بالا، تغییرات قدیمی و منابع frozen؛ حذف دستی Git آن ممنوع |
| `C:\Users\mehdi karani\AppData\Local\MAHOON-Protected-Review-20261016` | state محلی Worker/D1، backup، تنظیمات احتمالی حساس و شواهد/محتوای یکتای باقی‌مانده؛ خارج از بستهٔ portable |
| `C:\Backups\mahoon` و `tg-cms-local-archive` | backup/آرشیو محافظت‌شده؛ صرف شباهت نام دلیل حذف نیست |
| Tempهای audit/security/auto-publish/breaker و profileهای مرورگر | رسیدهای امنیتی، دادهٔ حساس یا یکتایی که دورریختنی بودن آن اثبات نشده است |
| `E:\Project\VsCode-Project\3-MahoonBot` | پروژهٔ جداگانهٔ ربات/نسخه‌ها و تنظیمات آن؛ duplicate همین repository فرض نشد |
| `E:\Project\Mahoon\Mahoon Report` | اسناد انسانیِ یکتا؛ برای حذف یا انتشار محتوا خوانده نشد |
| state مشترک Codex، ابزارهای سراسری و cacheهای مشترک | متعلق به پروژه‌های دیگر/خود برنامه نیز هستند؛ cleanup عمومی انجام نشد |

فهرست کامل مسیرها، اندازه، زمان، remote/worktree و تصمیم در inventory نهایی و آرشیو machine-readable موجود است. برای کار عادی در MAHOON هیچ‌یک از مسیرهای بیرونی dependency سورس نیستند. بسته مستقل است؛ باقی‌ماندن آن‌ها دلیل ارجاع build به پوشهٔ قدیمی نیست.

### مانع دقیق سیاست ابزار

`C:\Users\mehdi karani\AppData\Local\Temp\mahoon-cleanup-20261016\verified-final-archive-copy.zip`

اندازه: **578,258,357 bytes**. SHA256: `EAF08F85800FE943184689753EAA2A32AA299BA0D85E5AE665DC2D6D23AE607F`.

این فایل یک کپی اضافیِ آرشیو نهایی برای آزمون انتقال است؛ تطبیق SHA256 با نسخهٔ canonical پاس شد. حذف guard‌شده دو بار با پیام **`blocked by policy`** توسط بازبینی خودکار ابزار رد شد؛ دلیل جزئی‌تری ارائه نشد. حذفِ همان فایل با روش جایگزین یا حذف recursive والد انجام نشد. کل state این مأموریت در `C:\Users\mehdi karani\AppData\Local\Temp\mahoon-cleanup-20261016` برای بررسی حفظ شده است؛ این بخش پاک‌سازی کامل نشده است. تعیین تکلیف این کپی به اقدام/مجوز واقعی مالک وابسته مانده، نه BOT_TOKEN یا تغییر production.

## آزمون‌ها و production

- Git fsck کامل: PASS؛ submodule=0، LFS pointer=0، object alternate=0. همهٔ HEADهای ثبت‌شده و تغییرات تاریخی حفظ شدند؛ origin=`https://github.com/alakipalakiii/tg-cms.git`.
- Node24.18.0/npm12.0.1، Python3.13.14، Git2.55.0.windows.2 در این رایانه استفاده شدند؛ CI فعلی Node22/Python3.12 است. نصب `npm ci` از lockfile پاس شد. npm12 برای install script اختیاری sharp هشدار داد؛ build واقعی بعد از نصب پاس شد و policy نصب سراسری عوض نشد.
- build از snapshot ثبت‌شده در canonical: PASS؛ full publisher **923 تست، صفر failure، 3 skip اختیاری، 532.565s**.
- VERIFY محلی و نسخهٔ منتقل‌شده: build، **50 تست مرتبط publisher**، تست workerd/D1 مرز Telegram و **4 تست launcher** همگی PASS. خواندن secret واقعی یا عملیات production در این تست‌ها انجام نشد.
- آزمون انتقال در مسیر دارای فاصله و فارسی: SETUP/VERIFY واقعی، Git مستقل، کپی و hash آرشیوهای ضروری PASS. کپیِ آرشیو پس از افزودن 66 رسانهٔ تاریخی دیگر نیز جداگانه SHA256=PASS شد؛ همان کپی اضافی اکنون policy-blocked باقی مانده است.
- خطاهای اولیهٔ harness مسیر/encoding و پارامتر ParseFile اصلاح و تست مجدد پاس شدند. بررسی اولیهٔ sitemap از مسیر اعلام‌نشده استفاده کرده بود و کلاینت پیش‌فرض urllib نیز403 گرفت؛ کلاینت خواندنی سازگار، sitemap اعلام‌شده در robots را با200 و بدنهٔ کامل خواند. این‌ها به‌عنوان corruption تولید تعبیر نشدند. شکست بازِ تست عملکردی باقی نمانده؛ مانع حذف فایل بالا باقی است.
- مشاهدهٔ مستقل production در `2026-10-16T19:26:32.067056+00:00`: revision206، journal201، active/pending=null، PUBLISH، breakerCLOSED. وب‌سایت **15b81db8-10a5-40d3-97d3-b4c9c813b6b5 در100%**؛ deployment **20c8652e-d637-495a-8659-b6a7e63499ed**؛ API **708ba338-168e-4f69-aa57-ce5a012e7432**، allocation/deployment هر دو نسبت به قبل یکسان‌اند.
- GETهای home/robots/sitemap.xml/RSS=200 با انتقال کامل؛ health/public listing/stats API=200، admin health=401. تست مخرب bot/admin، POST تلگرام، registration، dispatch، deploy، D1 write/restore یا تغییر workflow/secret انجام نشد. scheduler خودکار مستقل از این رایانه باقی است.

## تحویل

شاخه: `codex/portable-handoff`. commit پیاده‌سازی: **`bc66fe9a0f6ae42152d9d5048f37ace9aec89eef`**؛ baseline پذیرفته‌شده: `202df2e`. HEAD نهایی گزارش‌ها و نتیجهٔ fast-forward push در پیام تحویل و `local-output/delivery-receipt.json` ثبت می‌شود؛ فایل گزارش نمی‌تواند SHA commit حامل خودش را از پیش داشته باشد. تنظیم author فقط از repository موجود به تنظیم محلی همین clone منتقل شد؛ global Git config یا credential store تغییر نکرد.

برای رایانهٔ دوم: پوشهٔ کامل MAHOON شامل `.git` و `local-archive` را منتقل کنید؛ credential یا بخش Protected Review بیرونی را کپی نکنید. ابتدا `MAHOON-START.cmd`، سپس با اینترنت `MAHOON-SETUP.cmd` و در پایان `MAHOON-VERIFY.cmd` اجرا شود. برای ادامه در Codex همین پوشه را Open folder کنید. توقف/بستن گفت‌وگوی فعلی برای پاک‌سازی آیندهٔ workspaceهای قدیمی لازم است؛ آن‌ها را دستی پاک نکنید.

جزئیات: [راهنمای انتقال](MAHOON-TRANSFER-GUIDE-FA.md)، [گزارش portability](MAHOON-PORTABILITY-REPORT.md)، [manifest خلاصه](MAHOON-CLEANUP-MANIFEST.json). manifestهای دقیق مسیر و نتیجه در `local-archive/cleanup-audit-manifests.zip` با SHA256 `b0abc07a448dc01810f3327b954b34d9c7dda3f179060e554f17da0b17c3e961` هستند. آرشیو و فایل‌های شخصی در Git commit نمی‌شوند.

## تکمیل بررسی branch و stash

هر28 شاخهٔ محلی Git اصلی نیز با SHA اصلی در `archive/original-branch/*` حفظ شد تا fetch/prune آینده منشأ کار منتشرنشده را از بین نبرد. چهار stash با فایل‌های source بررسی‌شده به commitهای غیرفعال `archive/local-stash-*` منتقل شدند؛ stash stack اصلی تغییر نکرد. stash پنجم payload بالقوه حساس با نام `.token` و خروجی‌های خصوصی دارد: مقدار آن خوانده نشد و payload به بسته منتقل نشد؛ patch سه فایل source امن آن جداگانه حفظ شد. بررسی metadata مستقل ثابت کرد object آن فایل بالقوه حساس در object store بسته وجود ندارد و از هیچ ref آن قابل دسترس نیست. این stash کامل در Git مشترک محافظت‌شدهٔ قدیمی باقی مانده است.

`origin/HEAD` محلی از اشارهٔ کهنه به شاخهٔ UI به main رسمی اصلاح شد؛ این تغییر metadata محلی بود و branch یا تنظیمات GitHub را عوض نکرد. شاخه‌های آرشیوی و stashها هرگز به main merge یا روی GitHub push نمی‌شوند. fsck بعد از این نگه‌داری نیز پاس شد. اعداد footprint جدول در cutoff ثبت‌شده‌اند؛ metadata و گزارش‌های نهایی چند کیلوبایت و آرشیو audit حدود5MB به بسته اضافه می‌کنند.

## بازخوانی هنگام تحویل — ۲۰۲۶/۱۰/۱۷

commitهای ابزار و گزارش `bc66fe9` و `f6769f6` با fast-forward روی main ثبت شدند. سپس انتشار خودکار مستقل، main را تا `77df253e75cc800214910a41191c93833d8c876b` جلو برد؛ فقط هفت فایل `publisher-state` تغییر کرده بودند و workspace نهایی با fast-forward همگام شد. کد سایت، API و workflow تغییری نکرد.

مشاهدهٔ خواندنی `2026-10-17T15:51:58.493069+00:00`: آخرین revision ورودی **212**، منتشرشده **211** با **1862 رکورد و 4271 مسیر**؛ journal **221**، active/pending=null، PUBLISH، breaker CLOSED. نسخهٔ سایت **`0c195e05-0940-4e70-a598-f3340d401989` در100%**، deployment **`a379de66-72cf-4cfc-b112-febc28c1007b`**؛ API و deployment آن با baseline قبلی یکسان‌اند. اجرای واقعی schedule **`39035724675`** SUCCESS است؛ pre-promotion-proof، production-proof، final-persistence و scheduled-circuit-breaker همگی SUCCESS هستند. این خواندن‌ها جای ممیزی مجدد کل شواهد immutable آن انتشار نیستند؛ این مأموریت هیچ dispatch یا mutation تولید انجام نداد. revision212 در cutoff هنوز منتشر نشده است؛ برای دنبال‌کردن ورودی‌های تازه تراکنش جدیدی اجرا نشد.

شواهد تکمیلی و SHA نهایی تحویل در `local-output/delivery-receipt.json`، `delivery-production-baseline.json`، `delivery-health.json` و `delivery-scheduled-run.json` نگه داشته می‌شوند. آمار پاک‌سازی و حجم دیسک بالا متعلق به cutoff اندازه‌گیری قبلی‌اند و به تاریخ جدید نسبت داده نمی‌شوند.
