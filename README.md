# مجله هنری ماهون

این مخزن مربوط به پروژه «مجله هنری ماهون» است. سایت با Astro ساخته شده و محتوای نوشته‌ها را از یک API جداگانه دریافت می‌کند.

## ساختار کلی پروژه

- مسیر سایت Astro:

  ```bash
  website/dreary-disk
  ```

- سایت اصلی:

  ```text
  https://mahoon-art-magazine.morentoofficial.workers.dev
  ```

- API Worker:

  ```text
  https://tg-cms-api.morentoofficial.workers.dev
  ```

## نحوه کار سایت و API

سایت Astro پست‌ها را مستقیماً از API می‌خواند. یعنی محتوای قابل نمایش در سایت از Worker API دریافت می‌شود و خود سایت مسئول نمایش آن محتوا است.

در حال حاضر API Worker جداگانه در Cloudflare مدیریت می‌شود. برای تغییرات مربوط به API، Worker، متغیرهای Cloudflare یا تنظیمات محیطی باید با احتیاط جداگانه عمل شود و این موارد بخشی از build عادی سایت Astro نیستند.

## SEO و آدرس‌های عمومی

سایت از `SITE.url` به‌عنوان آدرس رسمی پروژه استفاده می‌کند. آدرس‌های canonical، robots، sitemap، Open Graph URL و JSON-LD باید از همین مقدار ساخته شوند تا خروجی سایت در محیط‌های مختلف یکسان و قابل اعتماد بماند.

صفحه مقاله برای HTML اولیه، metaهای اختصاصی مثل `title`، `description`، `canonical`، `og:type` و `og:image` تولید می‌کند. این metaهای SSR از endpoint عمومی زیر خوانده می‌شوند:

```text
GET /seo/post/:slug
```

نمایش client-side مقاله همچنان حفظ شده است. endpoint عمومی `GET /post/:slug` برای نمایش و خواندن کاربر استفاده می‌شود و ممکن است `view_count` را افزایش دهد؛ بنابراین برای SSR meta نباید از `/post/:slug` استفاده شود.

## build سایت

برای ساخت نسخه قابل انتشار سایت:

```bash
cd website/dreary-disk
npm run build
```

## deploy سایت

برای deploy سایت، از مسیر سایت Astro دستور زیر اجرا می‌شود:

```bash
npm run deploy
```

## نکات امنیتی

هیچ Secret، Token، Password یا Cloudflare Variable نباید وارد GitHub شود. اطلاعات حساس باید فقط در محل امن و مناسب خود، مثل تنظیمات محیطی Cloudflare، نگهداری شوند.

## پنل ادمین و حذف امن

پنل ادمین برای مدیریت پست‌های مجله ماهون استفاده می‌شود. حذف پست‌ها در این پروژه به‌صورت soft delete انجام می‌شود، نه hard delete.

پست‌های حذف‌شده از تب «حذف‌شده‌ها» در پنل ادمین قابل مشاهده و بازگردانی هستند.

کد ثابت هر پست همان `id` دیتابیس است و همان کدی است که در ربات استفاده می‌شود. این ID بعد از حذف یا restore تغییر نمی‌کند.
