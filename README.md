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
