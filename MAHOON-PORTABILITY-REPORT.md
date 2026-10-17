# گزارش قابلیت انتقال MAHOON

> سابقهٔ انتقال قبلی: MAIN مستقل جای پوشهٔ C را گرفته است؛ راهنمای جاری در `MAHOON-TRANSFER-GUIDE-FA.md` و نتایج آزمون تازه در BACKUP/FINAL-VERIFICATION-RESULT.json است. آرشیوهای غیرعملیاتی به BACKUP منتقل شده‌اند و dependency MAIN نیستند.

**PORTABILITY: PASS — با آزمون واقعی مسیر دیگر در ویندوز.**

پوشهٔ مرجع: **`C:\Users\mehdi karani\MAHOON`**. commit پیاده‌سازی: `bc66fe9a0f6ae42152d9d5048f37ace9aec89eef`. وضعیت cleanup کامل را جداگانه در [گزارش پاک‌سازی](MAHOON-CLEANUP-REPORT.md) بخوانید؛ مانع policy حذف یک کپی آزمایشی، عملکرد بستهٔ قابل‌حمل را مختل نمی‌کند.

## محتویات و استقلال

- سورس کامل، workflowها و state پذیرفته‌شده، تست‌ها، lockfile، مستندات، برند سایت و تاریخچهٔ Git موجود است. ساختار importها و CI جابه‌جا نشده است.
- `.git` واقعی و مستقل با origin رسمی است؛ هیچ `.git` pointer به worktree، alternate object store، submodule یا LFS pointer نیازمند دانلود وجود ندارد. 31 HEAD تاریخی و تغییرات یکتای قدیمی جدا از source فعال نگه داشته شدند.
- `local-archive` شامل آرشیو source تاریخی، 631 رسانهٔ یکتا و 9 طراحی اصلی با SHA256 و provenance است؛ خارج از Git است و هنگام **کپی پوشه** همراه آن منتقل شود. clone تازهٔ GitHub به‌تنهایی حاوی این آرشیوهای شخصی نیست.
- Node/Python کامل، browser cache/profile، node_modules یا buildهای بزرگ داخل بسته حمل نمی‌شوند. dependencyهای قفل‌شده را SETUP بازسازی می‌کند؛ setup هیچ ابزار سراسری نصب/حذف یا رجیستری ویندوز را تغییر نمی‌دهد.

## آزمون انتقال واقعی

| بررسی | نتیجه |
|---|---|
| کپی به مسیر جدا با فاصله و واژهٔ فارسی «آزمون» | PASS |
| اجرای CMD از cwd نامرتبط و تشخیص root نسبی | PASS |
| SETUP با npm ci و checksumهای lockfile | PASS |
| build Astro از snapshot ثبت‌شده در مسیر منتقل‌شده | PASS |
| 50 تست publisher شامل proof/output/watcher/contract و شکست‌های واقعی fixture | PASS |
| workerd/D1: auth/source/replay/restore/media در fixture بدون شبکهٔ production | PASS |
| 4 تست launcher: parser، cwd، نپذیرفتن Deploy، نبود مسیر ماشین قدیمی | PASS |
| fsck و Git مستقل در copy | PASS |
| کپی و SHA256 آرشیوهای ضروری، سپس SHA256 آرشیو نهاییِ رسانه‌ها | PASS |
| حذف copy اصلی انتقال، dependencyها و cacheهای ایجادشده برای آزمون | PASS |
| حذف آخرین کپی ZIP مستقل، پس از تأیید hash | **BLOCKED_BY_AUTOMATIC_APPROVAL؛ حفظ‌شده، خارج از بسته** |

نسخهٔ کامل source در canonical نیز 923 تست publisher با صفر شکست و3 skip اختیاری را پاس کرد. build و آزمون‌های مربوط به Telegram در دو root پاس شدند. full production crawl/deploy، آزمون مخرب، ارسال پست واقعی و اتصال به credentialهای واقعی بخشی از شبیه‌سازی انتقال نبودند. source وب‌سایت، API، publisher، workflow و state production هیچ diff اجرایی ندارند.

## راه‌اندازی مقصد

1. پوشهٔ کامل را به یک مسیر user-writable کپی کنید؛ `.git` مخفی و `local-archive` حذف نشوند. بسته حدود0.62GB است؛ credentialهای ماشین قدیمی و Protected Review منتقل نشوند.
2. Git for Windows، Node22.12+ یا24، Python3.12 یا3.13 و Codex را از روش مورداعتماد خود نصب/باز کنید. CI از Node22/Python3.12 استفاده می‌کند؛ در این رایانه Node24/Python3.13 نیز واقعاً تست شد.
3. همان پوشه را در Codex Open folder کنید؛ `MAHOON-START.cmd` را اجرا کنید.
4. با اینترنت `MAHOON-SETUP.cmd` و سپس `MAHOON-VERIFY.cmd` را اجرا کنید. نبود ابزار یا dependency به STOPPED با exit غیرصفر منجر می‌شود؛ هیچ fallback برای deploy یا credential وجود ندارد.
5. حساب Codex/GitHub/Cloudflare در صورت نیاز به فعالیت مدیریتی آینده از ورود رسمی همان provider وصل شود. GitHub CLI برای build محلی لازم نیست. Git author metadata محلی حفظ شده است؛ authentication ماشین از credential store منتقل نشده است.

اجرای کامل آفلاین وعده داده نمی‌شود؛ registry، GitHub، Cloudflare و محتوای بیرونی نیازمند اینترنت‌اند. build محلی از snapshot ثبت‌شده، جای proof کامل نسخهٔ زنده را نمی‌گیرد. گزارش‌های production فقط در cutoff اعلام‌شده معتبرند؛ پیش از کار عملیاتی دوباره journal و نسخهٔ زنده بررسی شوند.

## امنیت و استثناها

هیچ BOT_TOKEN، ADMIN_TOKEN، webhook secret، Cloudflare token، cookie/profile، `.env` واقعی، SSH private key یا credential store به بسته منتقل نشد. secretهای production در provider باقی ماندند. source/fixtureها نام متغیرها و مقادیر ساختگی تست را دارند؛ این‌ها credential production نیستند. آرشیوهای تاریخی اجرا یا خودکار merge نشوند.

سه مسیر Git/workspace قدیمی برای نشست فعال و Git مشترک، بخش Protected Review، backupها، اسناد انسانی و پروژهٔ مستقل ربات بیرون بسته باقی مانده‌اند. runtime ابزارهای جدید هیچ ارجاعی به آن‌ها ندارد؛ حفظ آن‌ها به معنی وابستگی پروژه به رایانهٔ قدیمی نیست. برای نگه‌داشتن سابقهٔ گفت‌وگو از حساب Codex استفاده شود؛ کپی session database، browser profile یا credential داخلی Codex انجام نشد.

دستور حذف آخرین ZIP آزمایشی دو بار با `blocked by policy` رد شد؛ دور زدن کنترل یا حذف والد انجام نشد. این فایل و مسیر دقیقش در manifest و گزارش cleanup ثبت‌اند. برای بهره‌برداری از بستهٔ قابل‌حمل اقدام امنیتی دیگری لازم نیست؛ تعیین تکلیف استثناهای حذف باید مستقل و با رعایت نشست‌های فعال انجام شود.

## نگه‌داری نهایی تاریخچه

علاوه بر31 HEAD worktree، هر28 شاخهٔ محلی اصلی در refs آرشیوی و چهار stash بررسی‌شده به‌صورت commit غیرفعال در Git مستقل حفظ شدند. یک stash با payload بالقوه حساس صرفاً در اصل محافظت‌شده باقی ماند؛ patch source امن آن جداگانه داخل آرشیو محلی هست. خود object فایل بالقوه حساس در Git بسته وجود ندارد؛ هیچ مقدار credential برای این تشخیص خوانده نشد. `origin/HEAD=origin/main` و fsck پس از تغییر refs دوباره بررسی شدند. این refs تاریخی به production اعمال یا روی GitHub push نمی‌شوند.

## به‌روزرسانی تحویل — ۲۰۲۶/۱۰/۱۷

ابزارها و گزارش‌ها با `bc66fe9` و `f6769f6` روی main push شدند. ثبت‌های خودکار بعدی publisher فقط هفت فایل state را تغییر دادند؛ بسته با main در `77df253` fast-forward شد. هیچ تغییر اجرایی تازه‌ای پس از آزمون انتقال ایجاد نشد. نسخهٔ دقیق نهایی در `local-output/delivery-receipt.json` ثبت می‌شود.

در بازخوانی مستقل `2026-10-17T15:51:58.493069+00:00`، انتشار خودکار به revision211 رسیده، journal221 بدون active/pending و breakerCLOSED است؛ ورودی212 هنوز منتشر نشده است. سایت `0c195e05-0940-4e70-a598-f3340d401989` در100% است و API امن قبلی تغییر نکرده. schedule واقعی `39035724675` و گیت‌های proof/persistence/breaker آن SUCCESS هستند. این تحویل نشر تازه یا تغییر production انجام نمی‌دهد؛ snapshot206 در بخش‌های قبلی، cutoff تاریخی آزمون/اندازه‌گیری است.
