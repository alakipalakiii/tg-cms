# قوانین کار برای Codex

این فایل قوانین مهم کار روی پروژه «مجله هنری ماهون» را مشخص می‌کند. هدف این است که تغییرات کوچک، قابل فهم، قابل تست و امن باشند.

## منطق شماره پست‌ها

کد مطلب سایت همان `id` دیتابیس است و با شماره‌ای که در ربات استفاده می‌شود یکی است.

```text
کد مطلب سایت = id دیتابیس = شماره ربات
```

برای حذف، انتشار، ویرایش یا draft کردن یک مطلب، هیچ وقت نباید از `telegram_message_id` یا ترتیب نمایش استفاده شود.

عملیات مدیریتی فقط باید با `id` دیتابیس انجام شود.

## قوانین حذف و بازگردانی در ربات

حذف با ربات باید همیشه دو مرحله‌ای بماند:

```text
/delete 24
```

فقط پیش‌نمایش حذف را نشان می‌دهد و نباید حذف واقعی انجام دهد.

```text
/delete confirm 24
```

حذف واقعی را انجام می‌دهد.

برای بازگردانی مطلب حذف‌شده:

```text
/restore 24
```

برای دیدن مطالب حذف‌شده:

```text
/deleted
```

## قوانین Deleted / Restore

hard delete ممنوع است.

bulk hard delete ممنوع است.

حذف و restore فقط باید با `id` دیتابیس جدول `posts` انجام شود.

برای delete، restore یا edit هیچ وقت از `telegram_message_id` استفاده نکن.

ستون `deleted_at` برای soft delete استفاده می‌شود.

restore یعنی:

```sql
deleted_at = NULL
is_published = 1
```

`PATCH` عمومی نباید برای restore پست حذف‌شده باز شود. Restore باید از مسیر مشخص و امن خودش انجام شود.

endpointهای admin باید با `ADMIN_TOKEN` محافظت شوند.

قبل از هر تغییر بزرگ در Worker یا D1، بکاپ D1 لازم است.

## قوانین SEO

برای SSR meta مقاله هرگز از `/post/:slug` استفاده نکن، چون ممکن است `view_count` را افزایش دهد.

برای SSR meta مقاله فقط باید از endpoint زیر استفاده شود:

```text
GET /seo/post/:slug
```

endpoint SEO باید read-only بماند و نباید `UPDATE`، `INSERT` یا `DELETE` انجام دهد.

endpoint SEO نباید `view_count` را تغییر دهد.

lookup در endpoint SEO فقط باید با `slug` و query parameter یا bind امن انجام شود.

endpoint SEO نباید فیلدهای admin-only مثل `admin_note`، `chat_id`، `chat_title`، `deleted_at` یا `telegram_message_id` را خروجی بدهد.

تغییرات SEO نباید منطق admin، delete، restore، Telegram، D1 یا منطق ID ثابت را تغییر دهد.

`SITE.url` منبع رسمی canonical و URLهای عمومی سایت است.

## قوانین تغییر کد

هر تغییر کدنویسی باید کوچک و قابل تست باشد.

قبل از هر تغییر اجرایی، باید توضیح داده شود که چه فایلی تغییر می‌کند و چرا.

بعد از هر تغییر در سایت، تست build باید اجرا شود:

```bash
cd website/dreary-disk
npm run build
```

## قوانین امنیتی

هیچ Secret، Token، Password یا Cloudflare Variable نباید commit شود.

هیچ Secret، Token، Password، Database ID واقعی یا مقدار واقعی Cloudflare نباید وارد GitHub شود.

به Cloudflare، Secretها، Tokenها، Passwordها و متغیرهای محیطی نباید بدون درخواست روشن و مشخص کاربر دست زده شود.
