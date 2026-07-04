# Google Search Console Readiness - Mahoon Art Magazine

این سند چک‌لیست آماده‌سازی پروژه «مجله هنری ماهون» برای Google Search Console و تست نهایی indexability است. این سند فقط عملیاتی و مستنداتی است و هیچ تنظیم، deploy، migration یا تغییری در Cloudflare انجام نمی‌دهد.

## 1. وضعیت فعلی پروژه

- Site Worker URL:

  ```text
  https://mahoon-art-magazine.morentoofficial.workers.dev
  ```

- API Worker URL:

  ```text
  https://tg-cms-api.morentoofficial.workers.dev
  ```

- دامنه نهایی برنامه‌ریزی‌شده:

  ```text
  https://mahoonartmagazine.ir
  ```

- وضعیت دامنه:

  ```text
  خریداری شده، در انتظار فعال‌سازی
  ```

نکته مهم: تا قبل از فعال شدن دامنه، `SITE.url` و `SITE_PUBLIC_URL` نباید تغییر کنند. مقدار فعلی `SITE.url` باید همان آدرس workers.dev سایت باقی بماند.

## 2. وضعیت SEO انجام‌شده

چک‌لیست وضعیت فعلی:

- Base metadata
- canonical
- Open Graph
- Twitter Card
- robots.txt
- dynamic sitemap.xml
- RSS feed
- RSS autodiscovery link
- Article SSR metadata
- Article JSON-LD
- no private/admin fields in SEO outputs
- no SSR view_count increment

## 3. URLهای تست فعلی روی workers.dev

URLهای اصلی برای تست:

```text
https://mahoon-art-magazine.morentoofficial.workers.dev/
https://mahoon-art-magazine.morentoofficial.workers.dev/robots.txt
https://mahoon-art-magazine.morentoofficial.workers.dev/sitemap.xml
https://mahoon-art-magazine.morentoofficial.workers.dev/rss.xml
```

یک نمونه URL مطلب واقعی از sitemap فعلی:

```text
https://mahoon-art-magazine.morentoofficial.workers.dev/post/%D8%AE%D9%88%D8%AF%D8%AA-%D8%B1%D8%A7-%D8%A8%D8%A8%DB%8C%D9%86-1783163604498
```

اگر این نمونه در آینده حذف یا slug آن تغییر کرد، یک URL جدید از `/sitemap.xml` بردار.

## 4. دستورات CMD برای تست نهایی indexability

robots:

```cmd
curl -i "https://mahoon-art-magazine.morentoofficial.workers.dev/robots.txt?v=gsc-audit-1"
```

sitemap:

```cmd
curl -i "https://mahoon-art-magazine.morentoofficial.workers.dev/sitemap.xml?v=gsc-audit-1"
```

check posts in sitemap:

```cmd
curl -s "https://mahoon-art-magazine.morentoofficial.workers.dev/sitemap.xml?v=gsc-audit-1" | findstr /i /c:"/post/"
```

rss:

```cmd
curl -i "https://mahoon-art-magazine.morentoofficial.workers.dev/rss.xml?v=gsc-audit-1"
```

homepage html:

```cmd
mkdir C:\Temp
curl -s "https://mahoon-art-magazine.morentoofficial.workers.dev/?v=gsc-audit-1" > C:\Temp\mahoon-home-gsc.html
```

check canonical/OG/Twitter/RSS:

```cmd
findstr /i /c:"canonical" /c:"og:title" /c:"twitter:card" /c:"application/rss+xml" C:\Temp\mahoon-home-gsc.html
```

post html:

```cmd
curl -s "https://mahoon-art-magazine.morentoofficial.workers.dev/post/%D8%AE%D9%88%D8%AF%D8%AA-%D8%B1%D8%A7-%D8%A8%D8%A8%DB%8C%D9%86-1783163604498?v=gsc-audit-1" > C:\Temp\mahoon-post-gsc.html
```

check Article schema:

```cmd
findstr /i /c:"application/ld+json" /c:"schema.org" /c:"Article" C:\Temp\mahoon-post-gsc.html
```

check noindex absence:

```cmd
findstr /i /c:"noindex" C:\Temp\mahoon-home-gsc.html C:\Temp\mahoon-post-gsc.html
```

check private fields absence:

```cmd
findstr /i /c:"admin_note" /c:"telegram_message_id" /c:"chat_id" /c:"chat_title" /c:"deleted_at" /c:"view_count" C:\Temp\mahoon-home-gsc.html C:\Temp\mahoon-post-gsc.html
```

## 5. معیار قبولی تست‌ها

- robots باید status `200` و `Content-Type: text/plain` داشته باشد.
- robots باید `Sitemap` absolute داشته باشد.
- robots باید `/admin` و `/admin/` را برای crawl کنترل کند.
- sitemap باید status `200` و `Content-Type` مناسب XML داشته باشد.
- sitemap باید URLهای `/post/` داشته باشد.
- sitemap نباید `/admin` داشته باشد.
- rss باید status `200` و RSS XML معتبر داشته باشد.
- homepage باید canonical، Open Graph، Twitter Card و RSS autodiscovery link داشته باشد.
- صفحه post باید Article JSON-LD داشته باشد.
- `noindex` نباید در HTML صفحه اصلی یا صفحه مطلب دیده شود.
- private fields نباید در HTML خروجی دیده شوند.

## 6. برنامه اتصال دامنه بعد از فعال شدن mahoonartmagazine.ir

مراحل پیشنهادی:

1. Add site در Cloudflare
2. تغییر nameserver در پنل دامنه/ایرنیک
3. فعال شدن zone در Cloudflare
4. اتصال custom domain به Worker سایت `mahoon-art-magazine`
5. تست `https://mahoonartmagazine.ir`
6. تست `https://www.mahoonartmagazine.ir` در صورت تصمیم برای www
7. تصمیم canonical

   پیشنهاد:

   ```text
   https://mahoonartmagazine.ir
   ```

8. تغییر `SITE.url` در `website/dreary-disk/src/config.ts`
9. تغییر `SITE_PUBLIC_URL` در API Worker
10. build/deploy سایت
11. تست robots/sitemap/rss/canonical با دامنه جدید
12. commit/push تغییرات دامنه

## 7. Google Search Console بعد از فعال شدن دامنه

مراحل پیشنهادی:

1. Add Property
2. انتخاب Domain Property برای `mahoonartmagazine.ir`
3. دریافت DNS TXT verification
4. افزودن TXT در Cloudflare DNS
5. Verify در Search Console
6. Submit sitemap:

   ```text
   https://mahoonartmagazine.ir/sitemap.xml
   ```

7. URL Inspection برای:

   ```text
   https://mahoonartmagazine.ir/
   https://mahoonartmagazine.ir/sitemap.xml
   ```

   و یکی از URLهای `/post/`

8. Request Indexing برای homepage و چند post مهم
9. بررسی Pages report و Sitemaps report بعد از چند روز

## 8. نکات مهم

- تا فعال شدن دامنه، Search Console را برای دامنه نهایی انجام نده.
- نسخه workers.dev فقط برای تست فنی است.
- canonical نهایی باید بعد از اتصال دامنه به `mahoonartmagazine.ir` تغییر کند.
- RSS را در Search Console به عنوان sitemap معرفی نکن.
- `/admin` نباید در sitemap باشد.
- robots.txt ابزار امنیتی نیست؛ فقط برای راهنمای crawl است.
- اطلاعات محرمانه نباید وارد HTML، RSS، Sitemap یا Schema شود.
- هیچ Secret، Token، Password، Database ID واقعی یا Cloudflare Variable نباید وارد GitHub شود.
