const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Admin-Token"
};

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      ...CORS_HEADERS,
      "Content-Type": "application/json; charset=utf-8"
    }
  });
}

function textResponse(message, status = 200) {
  return new Response(message, {
    status,
    headers: {
      ...CORS_HEADERS,
      "Content-Type": "text/plain; charset=utf-8"
    }
  });
}

function cleanText(value) {
  if (!value) return "";
  return String(value).trim();
}

function normalizeDigits(value) {
  return String(value || "")
    .replace(/۰/g, "0")
    .replace(/۱/g, "1")
    .replace(/۲/g, "2")
    .replace(/۳/g, "3")
    .replace(/۴/g, "4")
    .replace(/۵/g, "5")
    .replace(/۶/g, "6")
    .replace(/۷/g, "7")
    .replace(/۸/g, "8")
    .replace(/۹/g, "9")
    .replace(/٠/g, "0")
    .replace(/١/g, "1")
    .replace(/٢/g, "2")
    .replace(/٣/g, "3")
    .replace(/٤/g, "4")
    .replace(/٥/g, "5")
    .replace(/٦/g, "6")
    .replace(/٧/g, "7")
    .replace(/٨/g, "8")
    .replace(/٩/g, "9");
}

function makeTitle(text) {
  const clean = cleanText(text);
  if (!clean) return "پست بدون عنوان";

  return clean
    .split("\n")[0]
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 90);
}

function makeExcerpt(text) {
  const clean = cleanText(text).replace(/\n/g, " ").replace(/\s+/g, " ");
  return clean.length > 180 ? clean.slice(0, 180) + "..." : clean;
}

function makeSlug(text) {
  const base = cleanText(text)
    .toLowerCase()
    .replace(/[^a-z0-9\u0600-\u06FF\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 70);

  const safeBase = base || "post";
  return `${safeBase}-${Date.now()}`;
}

function sanitizeSlug(value) {
  const base = cleanText(value)
    .toLowerCase()
    .replace(/[^a-z0-9\u0600-\u06FF\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 90);

  return base || "";
}

function getTelegramSource(update) {
  return (
    update.channel_post ||
    update.message ||
    update.edited_channel_post ||
    update.edited_message ||
    null
  );
}

function getBestPhoto(source) {
  if (!source?.photo || !Array.isArray(source.photo) || source.photo.length === 0) {
    return null;
  }

  return source.photo[source.photo.length - 1];
}

function extractMediaFromMessage(source) {
  const photo = getBestPhoto(source);

  if (photo) {
    return {
      media_type: "photo",
      media_file_id: photo.file_id || null,
      media_unique_id: photo.file_unique_id || null,
      media_mime_type: "image/jpeg",
      media_file_name: null,
      media_duration: null,
      media_width: photo.width || null,
      media_height: photo.height || null,
      media_size: photo.file_size || null,
      photo_file_id: photo.file_id || null,
      photo_unique_id: photo.file_unique_id || null,
      photo_width: photo.width || null,
      photo_height: photo.height || null
    };
  }

  if (source.video) {
    return {
      media_type: "video",
      media_file_id: source.video.file_id || null,
      media_unique_id: source.video.file_unique_id || null,
      media_mime_type: source.video.mime_type || "video/mp4",
      media_file_name: source.video.file_name || null,
      media_duration: source.video.duration || null,
      media_width: source.video.width || null,
      media_height: source.video.height || null,
      media_size: source.video.file_size || null,
      photo_file_id: null,
      photo_unique_id: null,
      photo_width: null,
      photo_height: null
    };
  }

  if (source.audio) {
    const audioCover = source.audio.thumbnail || source.audio.thumb || null;

    return {
      media_type: "audio",
      media_file_id: source.audio.file_id || null,
      media_unique_id: source.audio.file_unique_id || null,
      media_mime_type: source.audio.mime_type || "audio/mpeg",
      media_file_name: source.audio.file_name || source.audio.title || null,
      media_duration: source.audio.duration || null,
      media_width: null,
      media_height: null,
      media_size: source.audio.file_size || null,
      photo_file_id: audioCover?.file_id || null,
      photo_unique_id: audioCover?.file_unique_id || null,
      photo_width: audioCover?.width || null,
      photo_height: audioCover?.height || null
    };
  }

  if (source.voice) {
    return {
      media_type: "voice",
      media_file_id: source.voice.file_id || null,
      media_unique_id: source.voice.file_unique_id || null,
      media_mime_type: source.voice.mime_type || "audio/ogg",
      media_file_name: "voice.ogg",
      media_duration: source.voice.duration || null,
      media_width: null,
      media_height: null,
      media_size: source.voice.file_size || null,
      photo_file_id: null,
      photo_unique_id: null,
      photo_width: null,
      photo_height: null
    };
  }

  if (source.document) {
    return {
      media_type: "document",
      media_file_id: source.document.file_id || null,
      media_unique_id: source.document.file_unique_id || null,
      media_mime_type: source.document.mime_type || "application/octet-stream",
      media_file_name: source.document.file_name || "file",
      media_duration: null,
      media_width: null,
      media_height: null,
      media_size: source.document.file_size || null,
      photo_file_id: null,
      photo_unique_id: null,
      photo_width: null,
      photo_height: null
    };
  }

  if (source.animation) {
    return {
      media_type: "video",
      media_file_id: source.animation.file_id || null,
      media_unique_id: source.animation.file_unique_id || null,
      media_mime_type: source.animation.mime_type || "video/mp4",
      media_file_name: source.animation.file_name || null,
      media_duration: source.animation.duration || null,
      media_width: source.animation.width || null,
      media_height: source.animation.height || null,
      media_size: source.animation.file_size || null,
      photo_file_id: null,
      photo_unique_id: null,
      photo_width: null,
      photo_height: null
    };
  }

  return {
    media_type: null,
    media_file_id: null,
    media_unique_id: null,
    media_mime_type: null,
    media_file_name: null,
    media_duration: null,
    media_width: null,
    media_height: null,
    media_size: null,
    photo_file_id: null,
    photo_unique_id: null,
    photo_width: null,
    photo_height: null
  };
}


function telegramUnixToSqlDate(value) {
  const seconds = Number(value || 0);
  if (!seconds) return null;

  const date = new Date(seconds * 1000);
  if (Number.isNaN(date.getTime())) return null;

  return date.toISOString().slice(0, 19).replace("T", " ");
}

function extractTelegramPost(update) {
  const source = getTelegramSource(update);

  if (!source) return null;

  if (source.from?.is_bot) {
    return null;
  }

  if (source.text && String(source.text).trim().startsWith("/")) {
    return null;
  }

  const media = extractMediaFromMessage(source);

  const rawText =
    source.text ||
    source.caption ||
    media.media_file_name ||
    "";

  const text =
    cleanText(rawText) ||
    (media.media_type === "photo" ? "تصویر بدون توضیح" : "") ||
    (media.media_type === "video" ? "ویدیو بدون توضیح" : "") ||
    (media.media_type === "audio" ? "فایل صوتی بدون توضیح" : "") ||
    (media.media_type === "voice" ? "فایل صوتی بدون توضیح" : "") ||
    (media.media_type === "document" ? "فایل بدون توضیح" : "");

  if (!text && !media.media_file_id) return null;

  return {
    telegram_message_id: source.message_id || null,
    chat_id: source.chat?.id ? String(source.chat.id) : null,
    chat_title: source.chat?.title || source.chat?.username || "",
    chat_username: source.chat?.username || "",
    text,
    created_at_unix: source.date || Math.floor(Date.now() / 1000),
    created_at: telegramUnixToSqlDate(source.date),
    is_edited: Boolean(update.edited_channel_post || update.edited_message),
    ...media
  };
}


/* mahoon-public-category-filter-api */
function normalizePublicTag(tag) {
  return String(tag || "")
    .replace(/^#/, "")
    .replace(/[يى]/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/\u200c/g, "")
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function getPublicHashTags(text) {
  return Array.from(String(text || "").matchAll(/(^|\s)#([^\s#]+)/gu))
    .map((match) => match[2])
    .filter(Boolean);
}

function hasRequiredCategoryHashTag(text) {
  const categoryTags = new Set(
    mahoonScaleAllCategoryTagsV1().map(normalizePublicTag)
  );

  return getPublicHashTags(text)
    .map(normalizePublicTag)
    .some((tag) => categoryTags.has(tag));
}

function postWithMediaUrl(post, origin) {
  if (!post) return null;

  const resolvedMediaType = post.media_type || (post.photo_file_id ? "photo" : null);
  const isAudioLike = resolvedMediaType === "audio" || resolvedMediaType === "voice";

  const mediaFileId =
    post.media_file_id ||
    (!isAudioLike ? post.photo_file_id : null) ||
    null;

  const photoFileId = post.photo_file_id || null;

  const mediaUrl = mediaFileId
    ? `${origin}/media/${encodeURIComponent(mediaFileId)}`
    : null;

  const thumbnailUrl = photoFileId
    ? `${origin}/media/${encodeURIComponent(photoFileId)}`
    : null;

  return {
    ...post,
    media_type: resolvedMediaType,
    media_file_id: mediaFileId,
    media_url: mediaUrl,
    photo_url: resolvedMediaType === "photo" && thumbnailUrl ? thumbnailUrl : null,
    thumbnail_url: thumbnailUrl
  };
}

function seoPostPayload(post, origin) {
  const publicPost = postWithMediaUrl(post, origin);

  if (!publicPost) return null;

  return {
    id: publicPost.id,
    slug: publicPost.slug,
    text: publicPost.text,
    created_at: publicPost.created_at,
    updated_at: publicPost.updated_at,
    seo_title: publicPost.seo_title,
    seo_description: publicPost.seo_description,
    media_type: publicPost.media_type,
    media_url: publicPost.media_url,
    photo_url: publicPost.photo_url,
    media_mime_type: publicPost.media_mime_type,
    media_file_name: publicPost.media_file_name,
    media_width: publicPost.media_width || publicPost.photo_width || null,
    media_height: publicPost.media_height || publicPost.photo_height || null
  };
}

function rssPostPayload(post, origin) {
  const publicPost = postWithMediaUrl(post, origin);

  if (!publicPost) return null;

  return {
    id: publicPost.id,
    slug: publicPost.slug,
    text: publicPost.text,
    created_at: publicPost.created_at,
    updated_at: publicPost.updated_at,
    seo_title: publicPost.seo_title,
    seo_description: publicPost.seo_description,
    media_type: publicPost.media_type,
    media_url: publicPost.media_url,
    photo_url: publicPost.photo_url,
    media_mime_type: publicPost.media_mime_type,
    media_file_name: publicPost.media_file_name
  };
}

async function getTelegramFile(fileId, env) {
  if (!env.BOT_TOKEN) return null;

  const params = new URLSearchParams({
    file_id: fileId
  });

  const getFileUrl = `https://api.telegram.org/bot${env.BOT_TOKEN}/getFile?${params.toString()}`;
  const fileInfoResponse = await fetch(getFileUrl);

  if (!fileInfoResponse.ok) return null;

  const fileInfo = await fileInfoResponse.json();

  if (!fileInfo.ok || !fileInfo.result?.file_path) return null;

  const telegramFileUrl = `https://api.telegram.org/file/bot${env.BOT_TOKEN}/${fileInfo.result.file_path}`;
  const fileResponse = await fetch(telegramFileUrl);

  if (!fileResponse.ok) return null;

  return fileResponse;
}

function chooseTelegramUploadMethod(file) {
  const mime = file.type || "";

  if (mime.startsWith("image/")) {
    return {
      method: "sendPhoto",
      field: "photo"
    };
  }

  if (mime.startsWith("video/")) {
    return {
      method: "sendVideo",
      field: "video"
    };
  }

  if (mime.startsWith("audio/")) {
    return {
      method: "sendAudio",
      field: "audio"
    };
  }

  return {
    method: "sendDocument",
    field: "document"
  };
}

async function uploadAdminFileToTelegram(file, env) {
  if (!env.BOT_TOKEN) {
    throw new Error("BOT_TOKEN is not set");
  }

  if (!env.STORAGE_CHAT_ID) {
    throw new Error("STORAGE_CHAT_ID is not set");
  }

  const upload = chooseTelegramUploadMethod(file);

  const form = new FormData();
  form.append("chat_id", env.STORAGE_CHAT_ID);
  form.append(upload.field, file, file.name || "mahoon-file");
  form.append("disable_notification", "true");

  const res = await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/${upload.method}`, {
    method: "POST",
    body: form
  });

  const data = await res.json();

  if (!res.ok || !data.ok || !data.result) {
    throw new Error(data.description || "Telegram upload failed");
  }

  const media = extractMediaFromMessage(data.result);

  if (!media.media_file_id) {
    throw new Error("Telegram did not return file_id");
  }

  return media;
}

function getAdminToken(request) {
  const auth = request.headers.get("Authorization") || "";
  const bearer = auth.replace(/^Bearer\s+/i, "").trim();
  const custom = request.headers.get("X-Admin-Token") || "";

  return bearer || custom;
}

function requireAdmin(request, env) {
  const token = getAdminToken(request);

  if (!env.ADMIN_TOKEN) return false;

  return token === env.ADMIN_TOKEN;
}

const SITE_SETTING_KEYS = [
  "site_name",
  "header_description",
  "home_hero_line_one",
  "home_hero_line_two",
  "home_latest_title",
  "home_ad_right_enabled",
  "home_ad_right_button",
  "home_ad_right_position",
  "home_ad_right_image",
  "home_ad_left_enabled",
  "home_ad_left_button",
  "home_ad_left_position",
  "home_ad_left_image",
  "home_ad_right_title",
  "home_ad_right_text",
  "home_ad_right_url",
  "home_ad_left_title",
  "home_ad_left_text",
  "home_ad_left_url",
  "about_lead",
  "about_body",
  "contact_lead",
  "contact_body",
  "contact_cta_text",
  "footer_title",
  "footer_description",
  "footer_copyright",
  "telegram_url"
];

const SITE_SETTING_KEY_SET = new Set(SITE_SETTING_KEYS);

function isMissingSiteSettingsTable(error) {
  const message = String(error?.message || error || "").toLowerCase();
  return message.includes("site_settings") && (
    message.includes("no such table") ||
    message.includes("not found") ||
    message.includes("does not exist")
  );
}

function normalizeSiteSettingsPayload(body) {
  const source = body?.settings && typeof body.settings === "object" ? body.settings : body;
  const settings = {};

  for (const key of SITE_SETTING_KEYS) {
    if (Object.prototype.hasOwnProperty.call(source || {}, key)) {
      settings[key] = cleanText(source[key]);
    }
  }

  return settings;
}

async function readSiteSettings(env) {
  try {
    const { results } = await env.DB.prepare(
      `
      SELECT key, value
      FROM site_settings
      ORDER BY key ASC
      `
    ).all();

    return Object.fromEntries(
      (results || [])
        .filter(row => SITE_SETTING_KEY_SET.has(row.key))
        .map(row => [row.key, cleanText(row.value)])
    );
  } catch (error) {
    if (isMissingSiteSettingsTable(error)) return {};
    throw error;
  }
}

async function writeSiteSettings(env, settings) {
  const entries = Object.entries(settings).filter(([key]) => SITE_SETTING_KEY_SET.has(key));

  if (entries.length === 0) {
    return { changed: 0 };
  }

  const statements = entries.map(([key, value]) =>
    env.DB.prepare(
      `
      INSERT INTO site_settings (key, value, updated_at)
      VALUES (?, ?, CURRENT_TIMESTAMP)
      ON CONFLICT(key) DO UPDATE SET
        value = excluded.value,
        updated_at = CURRENT_TIMESTAMP
      `
    ).bind(key, value)
  );

  await env.DB.batch(statements);

  return { changed: entries.length };
}

function getTelegramAdminIds(env) {
  const values = [
    env.BOT_ADMIN_CHAT_ID || "",
    env.BOT_ADMIN_IDS || "",
    env.STORAGE_CHAT_ID || ""
  ];

  return new Set(
    values
      .join(",")
      .split(",")
      .map(item => normalizeDigits(String(item).trim()))
      .filter(Boolean)
  );
}

function isTelegramAdmin(source, env) {
  const allowed = getTelegramAdminIds(env);

  if (allowed.size === 0) return false;

  const chatId = source.chat?.id ? String(source.chat.id) : "";
  const fromId = source.from?.id ? String(source.from.id) : "";

  return allowed.has(chatId) || allowed.has(fromId);
}

async function sendTelegramMessage(chatId, message, env, replyToMessageId = null) {
  if (!env.BOT_TOKEN || !chatId) return;

  const form = new FormData();
  form.append("chat_id", String(chatId));
  form.append("text", String(message).slice(0, 3900));
  form.append("disable_web_page_preview", "true");

  if (replyToMessageId) {
    form.append("reply_to_message_id", String(replyToMessageId));
  }

  await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/sendMessage`, {
    method: "POST",
    body: form
  }).catch(() => null);
}

function buildPublicPostUrl(slug, env) {
  if (!slug) return "";

  const base = cleanText(env.SITE_PUBLIC_URL || "");

  if (!base) {
    return `/post/${slug}`;
  }

  return `${base.replace(/\/$/, "")}/post/${encodeURIComponent(slug)}`;
}

function commandHelpText() {
  return `دستورهای مدیریت ماهون:

قانون اصلی:
کد مطلب روی سایت همان id دیتابیس است و تنها شماره معتبر برای ربات است.
اعداد فارسی و انگلیسی هر دو پشتیبانی می‌شوند.

دیدن پست:
24
۲۴
#24
#۲۴
پست 24
پست ۲۴

یا:
/post 24
/status 24

آخرین پست:
/last

انتشار:
/publish 24

خروج از انتشار:
/draft 24

حذف امن دو مرحله‌ای:
مرحله ۱:
/delete 24

مرحله ۲:
/delete confirm 24

بازگردانی پست حذف‌شده:
/restore 24

لیست آخرین پست‌های حذف‌شده:
/deleted

تغییر آدرس:
/slug 24 slug-jadid

ویرایش متن:
/edit 24 متن جدید پست

نکته مهم:
هیچ دستور مدیریتی بدون کد مطلب اجرا نمی‌شود.`;
}

function postSummaryText(post, env) {
  if (!post) {
    return "پستی با این کد مطلب پیدا نشد.";
  }

  const status = post.deleted_at
    ? "حذف شده"
    : Number(post.is_published) === 1
      ? "منتشر شده"
      : "منتشر نشده";

  const media = post.media_type ? post.media_type : "بدون فایل";
  const title = makeTitle(post.text);
  const link = buildPublicPostUrl(post.slug, env);

  return `کد ثابت مطلب: #${post.id}

عنوان:
${title}

وضعیت: ${status}
نوع فایل: ${media}
بازدید: ${Number(post.view_count || 0)}

Slug:
${post.slug || "-"}

لینک:
${link || "-"}

دستورهای سریع:
/status ${post.id}
/draft ${post.id}
/publish ${post.id}
/delete ${post.id}
/delete confirm ${post.id}
/restore ${post.id}`;
}

async function getLastPost(env) {
  return await env.DB.prepare(
    `
    SELECT
      id,
      text,
      slug,
      created_at,
      updated_at,
      is_published,
      deleted_at,
      media_type,
      media_file_id,
      media_unique_id,
      media_mime_type,
      media_file_name,
      media_duration,
      media_width,
      media_height,
      media_size,
      photo_file_id,
      photo_unique_id,
      photo_width,
      photo_height,
      seo_title,
      seo_description,
      admin_note,
      COALESCE(view_count, 0) AS view_count,
      last_viewed_at
    FROM posts
    WHERE deleted_at IS NULL
    ORDER BY created_at DESC, id DESC
    LIMIT 1
    `
  ).first();
}

async function getPostById(env, id) {
  const safeId = Number(id);

  if (!Number.isInteger(safeId) || safeId <= 0) return null;

  return await env.DB.prepare(
    `
    SELECT
      id,
      text,
      slug,
      created_at,
      updated_at,
      is_published,
      deleted_at,
      media_type,
      media_file_id,
      media_unique_id,
      media_mime_type,
      media_file_name,
      media_duration,
      media_width,
      media_height,
      media_size,
      photo_file_id,
      photo_unique_id,
      photo_width,
      photo_height,
      seo_title,
      seo_description,
      admin_note,
      COALESCE(view_count, 0) AS view_count,
      last_viewed_at
    FROM posts
    WHERE id = ?
    LIMIT 1
    `
  ).bind(safeId).first();
}

async function getDeletedPosts(env) {
  const { results } = await env.DB.prepare(
    `
    SELECT
      id,
      text,
      slug,
      created_at,
      updated_at,
      is_published,
      deleted_at,
      media_type,
      media_file_id,
      media_unique_id,
      media_mime_type,
      media_file_name,
      media_duration,
      media_width,
      media_height,
      media_size,
      photo_file_id,
      photo_unique_id,
      photo_width,
      photo_height,
      seo_title,
      seo_description,
      admin_note,
      COALESCE(view_count, 0) AS view_count,
      last_viewed_at
    FROM posts
    WHERE deleted_at IS NOT NULL
    ORDER BY deleted_at DESC
    LIMIT 10
    `
  ).all();

  return results || [];
}

function parseFirstId(value) {
  const normalized = normalizeDigits(cleanText(value));
  const match = normalized.match(/(?:^|\s)#?(\d+)(?=\s|$)/);

  if (!match) return null;

  const id = Number(match[1]);

  return Number.isInteger(id) && id > 0 ? id : null;
}

function parseLookupByNumber(text) {
  const value = normalizeDigits(cleanText(text));

  let match = value.match(/^#?(\d+)$/);
  if (match) {
    return Number(match[1]);
  }

  match = value.match(/^(?:پست|شماره|کد|کد مطلب|post|id)\s+#?(\d+)$/i);
  if (match) {
    return Number(match[1]);
  }

  match = value.match(/^\/(?:post|get|show|id|status)(?:@\w+)?\s+#?(\d+)$/i);
  if (match) {
    return Number(match[1]);
  }

  return null;
}

function hasDeleteConfirmation(value) {
  const normalized = normalizeDigits(cleanText(value)).toLowerCase();

  return /(?:^|\s)(confirm|yes|ok|تایید|تأیید|بله)(?:\s|$)/i.test(normalized);
}

function parseBasicCommand(text) {
  const trimmed = cleanText(text);
  const normalized = normalizeDigits(trimmed);
  const match = normalized.match(/^\/([a-zA-Z_]+)(?:@\w+)?(?:\s+([\s\S]*))?$/);

  if (!match) {
    return null;
  }

  const originalMatch = trimmed.match(/^\/([a-zA-Z_]+)(?:@\w+)?(?:\s+([\s\S]*))?$/);

  const command = `/${match[1].toLowerCase()}`;
  const normalizedArgs = match[2] || "";
  const args = originalMatch?.[2] || normalizedArgs || "";
  const id = parseFirstId(normalizedArgs);

  return {
    command,
    args,
    normalizedArgs,
    id,
    confirm: hasDeleteConfirmation(normalizedArgs)
  };
}

function matchCommandWithIdAndRest(text, commandName) {
  const trimmed = cleanText(text);
  const re = new RegExp(`^\\/${commandName}(?:@\\w+)?\\s+#?([0-9۰-۹٠-٩]+)\\s+([\\s\\S]+)$`, "i");
  const match = trimmed.match(re);

  if (!match) return null;

  const id = Number(normalizeDigits(match[1]));

  if (!Number.isInteger(id) || id <= 0) return null;

  return {
    id,
    rest: cleanText(match[2])
  };
}

async function sendMissingIdMessage(chatId, command, env, replyId) {
  await sendTelegramMessage(
    chatId,
    `برای دستور ${command} باید کد ثابت مطلب را وارد کنی.

مثال درست:
${command} 24

عدد فارسی هم قابل قبول است:
${command} ۲۴

هیچ دستور مدیریتی بدون شماره اجرا نمی‌شود.`,
    env,
    replyId
  );
}

function deletedPostsListText(posts) {
  if (!posts || posts.length === 0) {
    return "هیچ پست حذف‌شده‌ای پیدا نشد.";
  }

  return `آخرین پست‌های حذف‌شده:

${posts
  .map(post => {
    return `#${post.id} — ${makeTitle(post.text)}
/restore ${post.id}
/status ${post.id}`;
  })
  .join("\n\n")}`;
}

async function handleTelegramManagementMessage(update, env) {
  const source = getTelegramSource(update);

  if (!source || !source.text) return null;

  const text = cleanText(source.text);
  const chatId = source.chat?.id ? String(source.chat.id) : "";
  const replyId = source.message_id || null;

  const directPostId = parseLookupByNumber(text);
  const isCommand = text.startsWith("/");

  if (!isCommand && !directPostId) {
    return null;
  }

  if (!isTelegramAdmin(source, env)) {
    await sendTelegramMessage(chatId, "این دستور مجاز نیست.", env, replyId);

    return json({
      ok: true,
      command: true,
      authorized: false
    });
  }

  if (directPostId) {
    const post = await getPostById(env, directPostId);
    await sendTelegramMessage(chatId, postSummaryText(post, env), env, replyId);

    return json({
      ok: true,
      command: true,
      action: "lookup",
      id: directPostId
    });
  }

  const basic = parseBasicCommand(text);

  if (!basic) {
    await sendTelegramMessage(chatId, commandHelpText(), env, replyId);
    return json({ ok: true, command: true });
  }

  const command = basic.command;
  const id = basic.id;

  if (command === "/help" || command === "/start") {
    await sendTelegramMessage(chatId, commandHelpText(), env, replyId);
    return json({ ok: true, command: true });
  }

  if (command === "/last") {
    const post = await getLastPost(env);
    await sendTelegramMessage(chatId, postSummaryText(post, env), env, replyId);

    return json({
      ok: true,
      command: true,
      action: "last"
    });
  }

  if (command === "/deleted") {
    const posts = await getDeletedPosts(env);
    await sendTelegramMessage(chatId, deletedPostsListText(posts), env, replyId);

    return json({
      ok: true,
      command: true,
      action: "deleted"
    });
  }

  if (command === "/post" || command === "/get" || command === "/show" || command === "/id" || command === "/status") {
    if (!id) {
      await sendMissingIdMessage(chatId, command, env, replyId);
      return json({ ok: true, command: true, action: "missing_id" });
    }

    const post = await getPostById(env, id);
    await sendTelegramMessage(chatId, postSummaryText(post, env), env, replyId);

    return json({
      ok: true,
      command: true,
      action: "lookup",
      id
    });
  }

  if (command === "/publish") {
    if (!id) {
      await sendMissingIdMessage(chatId, command, env, replyId);
      return json({ ok: true, command: true, action: "missing_id" });
    }

    const post = await getPostById(env, id);

    if (!post) {
      await sendTelegramMessage(chatId, "پستی با این کد مطلب پیدا نشد.", env, replyId);
      return json({ ok: true, command: true });
    }

    if (post.deleted_at) {
      await sendTelegramMessage(
        chatId,
        `این پست حذف شده است و با /publish منتشر نمی‌شود.

برای بازگردانی:
/restore ${post.id}`,
        env,
        replyId
      );

      return json({ ok: true, command: true, action: "publish_blocked_deleted", id: post.id });
    }

    await env.DB.prepare(
      `
      UPDATE posts
      SET is_published = 1, updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
      `
    ).bind(post.id).run();

    const fresh = await getPostById(env, post.id);
    await sendTelegramMessage(chatId, `پست منتشر شد.\n\n${postSummaryText(fresh, env)}`, env, replyId);

    return json({
      ok: true,
      command: true,
      action: "publish",
      id: post.id
    });
  }

  if (command === "/draft" || command === "/unpublish") {
    if (!id) {
      await sendMissingIdMessage(chatId, command, env, replyId);
      return json({ ok: true, command: true, action: "missing_id" });
    }

    const post = await getPostById(env, id);

    if (!post) {
      await sendTelegramMessage(chatId, "پستی با این کد مطلب پیدا نشد.", env, replyId);
      return json({ ok: true, command: true });
    }

    if (post.deleted_at) {
      await sendTelegramMessage(
        chatId,
        `این پست حذف شده است.

برای بازگردانی:
/restore ${post.id}`,
        env,
        replyId
      );

      return json({ ok: true, command: true, action: "draft_blocked_deleted", id: post.id });
    }

    await env.DB.prepare(
      `
      UPDATE posts
      SET is_published = 0, updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
      `
    ).bind(post.id).run();

    const fresh = await getPostById(env, post.id);
    await sendTelegramMessage(chatId, `پست از انتشار خارج شد.\n\n${postSummaryText(fresh, env)}`, env, replyId);

    return json({
      ok: true,
      command: true,
      action: "draft",
      id: post.id
    });
  }

  if (command === "/delete") {
    if (!id) {
      await sendMissingIdMessage(chatId, command, env, replyId);
      return json({ ok: true, command: true, action: "missing_id" });
    }

    const post = await getPostById(env, id);

    if (!post) {
      await sendTelegramMessage(chatId, "پستی با این کد مطلب پیدا نشد.", env, replyId);
      return json({ ok: true, command: true });
    }

    if (post.deleted_at) {
      await sendTelegramMessage(
        chatId,
        `این پست قبلاً حذف شده است.

${postSummaryText(post, env)}

برای بازگردانی:
/restore ${post.id}`,
        env,
        replyId
      );

      return json({
        ok: true,
        command: true,
        action: "already_deleted",
        id: post.id
      });
    }

    if (!basic.confirm) {
      await sendTelegramMessage(
        chatId,
        `پیش‌نمایش حذف امن

هیچ چیزی هنوز حذف نشده است.

${postSummaryText(post, env)}

برای حذف نهایی دقیقاً این دستور را بفرست:
/delete confirm ${post.id}

عدد فارسی هم قابل قبول است:
/delete confirm ${post.id}`,
        env,
        replyId
      );

      return json({
        ok: true,
        command: true,
        action: "delete_preview",
        id: post.id
      });
    }

    await env.DB.prepare(
      `
      UPDATE posts
      SET is_published = 0, deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
      `
    ).bind(post.id).run();

    const fresh = await getPostById(env, post.id);

    await sendTelegramMessage(
      chatId,
      `پست با کد ثابت #${post.id} حذف شد.

برای بازگردانی:
/restore ${post.id}

${postSummaryText(fresh, env)}`,
      env,
      replyId
    );

    return json({
      ok: true,
      command: true,
      action: "delete_confirmed",
      id: post.id
    });
  }

  if (command === "/restore") {
    if (!id) {
      await sendMissingIdMessage(chatId, command, env, replyId);
      return json({ ok: true, command: true, action: "missing_id" });
    }

    const post = await getPostById(env, id);

    if (!post) {
      await sendTelegramMessage(chatId, "پستی با این کد مطلب پیدا نشد.", env, replyId);
      return json({ ok: true, command: true });
    }

    if (!post.deleted_at) {
      await sendTelegramMessage(
        chatId,
        `این پست حذف‌شده نیست و همین حالا فعال است.

${postSummaryText(post, env)}`,
        env,
        replyId
      );

      return json({
        ok: true,
        command: true,
        action: "restore_not_needed",
        id: post.id
      });
    }

    await env.DB.prepare(
      `
      UPDATE posts
      SET is_published = 1, deleted_at = NULL, updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
      `
    ).bind(post.id).run();

    const fresh = await getPostById(env, post.id);

    await sendTelegramMessage(
      chatId,
      `پست با کد ثابت #${post.id} بازگردانی شد.

${postSummaryText(fresh, env)}`,
      env,
      replyId
    );

    return json({
      ok: true,
      command: true,
      action: "restore",
      id: post.id
    });
  }

  if (command === "/slug") {
    const parsed = matchCommandWithIdAndRest(text, "slug");

    if (!parsed) {
      await sendTelegramMessage(chatId, "فرمت درست:\n/slug 24 slug-jadid", env, replyId);
      return json({ ok: true, command: true });
    }

    const postId = parsed.id;
    const newSlug = sanitizeSlug(parsed.rest);

    if (!newSlug) {
      await sendTelegramMessage(chatId, "Slug معتبر نیست.", env, replyId);
      return json({ ok: true, command: true });
    }

    const post = await getPostById(env, postId);

    if (!post) {
      await sendTelegramMessage(chatId, "پستی با این کد مطلب پیدا نشد.", env, replyId);
      return json({ ok: true, command: true });
    }

    if (post.deleted_at) {
      await sendTelegramMessage(chatId, `این پست حذف شده است. اول آن را بازگردانی کن:\n/restore ${post.id}`, env, replyId);
      return json({ ok: true, command: true });
    }

    const duplicate = await env.DB.prepare(
      `
      SELECT id
      FROM posts
      WHERE slug = ?
      AND slug IS NOT NULL
      AND slug != ''
      AND id != ?
      LIMIT 1
      `
    ).bind(newSlug, postId).first();

    if (duplicate) {
      await sendTelegramMessage(chatId, "این Slug قبلاً استفاده شده است.", env, replyId);
      return json({ ok: true, command: true });
    }

    await env.DB.prepare(
      `
      UPDATE posts
      SET slug = ?, updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
      `
    ).bind(newSlug, postId).run();

    const fresh = await getPostById(env, postId);
    await sendTelegramMessage(chatId, `Slug تغییر کرد.\n\n${postSummaryText(fresh, env)}`, env, replyId);

    return json({
      ok: true,
      command: true,
      action: "slug",
      id: postId,
      slug: newSlug
    });
  }

  if (command === "/edit") {
    const parsed = matchCommandWithIdAndRest(text, "edit");

    if (!parsed) {
      await sendTelegramMessage(chatId, "فرمت درست:\n/edit 24 متن جدید پست", env, replyId);
      return json({ ok: true, command: true });
    }

    const postId = parsed.id;
    const newText = cleanText(parsed.rest);

    if (!newText) {
      await sendTelegramMessage(chatId, "متن جدید خالی است.", env, replyId);
      return json({ ok: true, command: true });
    }

    const post = await getPostById(env, postId);

    if (!post) {
      await sendTelegramMessage(chatId, "پستی با این کد مطلب پیدا نشد.", env, replyId);
      return json({ ok: true, command: true });
    }

    if (post.deleted_at) {
      await sendTelegramMessage(chatId, `این پست حذف شده است. اول آن را بازگردانی کن:\n/restore ${post.id}`, env, replyId);
      return json({ ok: true, command: true });
    }

    await env.DB.prepare(
      `
      UPDATE posts
      SET text = ?, updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
      `
    ).bind(newText, postId).run();
    await mahoonScaleSyncPostTagProjectionV1(env, postId, newText);

    const fresh = await getPostById(env, postId);
    await sendTelegramMessage(chatId, `متن پست ویرایش شد.\n\n${postSummaryText(fresh, env)}`, env, replyId);

    return json({
      ok: true,
      command: true,
      action: "edit",
      id: postId
    });
  }

  await sendTelegramMessage(chatId, commandHelpText(), env, replyId);

  return json({
    ok: true,
    command: true,
    action: "help"
  });
}

async function ensureUniqueSlug(env, slug, currentId = null) {
  if (!slug) return false;

  let existing;

  if (currentId) {
    existing = await env.DB.prepare(
      `
      SELECT id
      FROM posts
      WHERE slug = ?
      AND slug IS NOT NULL
      AND slug != ''
      AND id != ?
      LIMIT 1
      `
    ).bind(slug, currentId).first();
  } else {
    existing = await env.DB.prepare(
      `
      SELECT id
      FROM posts
      WHERE slug = ?
      AND slug IS NOT NULL
      AND slug != ''
      LIMIT 1
      `
    ).bind(slug).first();
  }

  return !existing;
}

function normalizeIds(ids) {
  if (!Array.isArray(ids)) return [];

  return ids
    .map(id => Number(normalizeDigits(id)))
    .filter(id => Number.isInteger(id) && id > 0);
}

function mediaFromBody(body) {
  const mediaType = cleanText(body.media_type);
  const mediaFileId = cleanText(body.media_file_id);

  if (!mediaType || !mediaFileId) {
    return {
      media_type: null,
      media_file_id: null,
      media_unique_id: null,
      media_mime_type: null,
      media_file_name: null,
      media_duration: null,
      media_width: null,
      media_height: null,
      media_size: null,
      photo_file_id: null,
      photo_unique_id: null,
      photo_width: null,
      photo_height: null
    };
  }

  return {
    media_type: mediaType,
    media_file_id: mediaFileId,
    media_unique_id: cleanText(body.media_unique_id) || null,
    media_mime_type: cleanText(body.media_mime_type) || null,
    media_file_name: cleanText(body.media_file_name) || null,
    media_duration: body.media_duration ? Number(body.media_duration) : null,
    media_width: body.media_width ? Number(body.media_width) : null,
    media_height: body.media_height ? Number(body.media_height) : null,
    media_size: body.media_size ? Number(body.media_size) : null,
    photo_file_id: mediaType === "photo" ? mediaFileId : null,
    photo_unique_id: mediaType === "photo" ? cleanText(body.media_unique_id) || null : null,
    photo_width: mediaType === "photo" && body.media_width ? Number(body.media_width) : null,
    photo_height: mediaType === "photo" && body.media_height ? Number(body.media_height) : null
  };
}

async function sendSavedPostConfirmation(update, telegramPost, savedPost, env) {
  const source = getTelegramSource(update);

  if (!source || !update.message) return;

  const message = `پست ذخیره شد.

${postSummaryText(savedPost, env)}`;

  await sendTelegramMessage(
    telegramPost.chat_id,
    message,
    env,
    telegramPost.telegram_message_id
  );
}


/* mahoon-analytics-api-v2 */
function mahoonAnalyticsCorsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Admin-Token",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS"
  };
}

function mahoonAnalyticsJson(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      ...mahoonAnalyticsCorsHeaders(),
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store"
    }
  });
}

function mahoonAnalyticsCleanText(value, maxLength = 500) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, maxLength);
}

function mahoonAnalyticsCleanPath(value) {
  const source = String(value || "/").trim();
  if (!source || !source.startsWith("/")) return "/";
  return source.slice(0, 400);
}

function mahoonAnalyticsHost(value) {
  try {
    const host = new URL(String(value || "")).hostname || "";
    return host.replace(/^www\./i, "").slice(0, 160);
  } catch {
    return "";
  }
}

function mahoonAnalyticsDevice(userAgent) {
  const ua = String(userAgent || "").toLowerCase();

  if (/bot|crawl|spider|slurp|facebookexternalhit|telegrambot|whatsapp|preview/.test(ua)) {
    return "bot";
  }

  if (/tablet|ipad/.test(ua)) return "tablet";
  if (/mobile|android|iphone|ipod/.test(ua)) return "mobile";

  return "desktop";
}

function mahoonAnalyticsPostSlug(pathname) {
  const match = String(pathname || "").match(/^\/post\/(.+)$/);
  if (!match) return "";

  try {
    return decodeURIComponent(match[1]).slice(0, 500);
  } catch {
    return match[1].slice(0, 500);
  }
}

function mahoonAnalyticsTag(pathname) {
  const match = String(pathname || "").match(/^\/tag\/(.+)$/);
  if (!match) return "";

  try {
    return decodeURIComponent(match[1]).slice(0, 300);
  } catch {
    return match[1].slice(0, 300);
  }
}

function mahoonAnalyticsAdminToken(request) {
  const direct = request.headers.get("X-Admin-Token") || "";
  const authorization = request.headers.get("Authorization") || "";
  const bearer = authorization.toLowerCase().startsWith("bearer ")
    ? authorization.slice(7).trim()
    : "";

  return direct || bearer;
}

function mahoonAnalyticsIsAdmin(request, env) {
  const expected = String(env.ADMIN_TOKEN || "").trim();
  const received = String(mahoonAnalyticsAdminToken(request) || "").trim();

  return Boolean(expected && received && expected === received);
}

async function mahoonTrackAnalytics(request, env) {
  if (!env.DB) {
    return mahoonAnalyticsJson({ ok: false, error: "DB binding is missing" }, 500);
  }

  let body: Record<string, any> = {};

  try {
    body = await request.json();
  } catch {
    body = {};
  }

  const eventType = mahoonAnalyticsCleanText(body.event_type || "page_view", 40) || "page_view";
  const pathname = mahoonAnalyticsCleanPath(body.path || "/");
  const url = mahoonAnalyticsCleanText(body.url || "", 900);
  const title = mahoonAnalyticsCleanText(body.title || "", 240);
  const referrer = mahoonAnalyticsCleanText(body.referrer || "", 900);
  const referrerHost = mahoonAnalyticsHost(referrer);
  const userAgent = mahoonAnalyticsCleanText(request.headers.get("User-Agent") || "", 700);
  const device = mahoonAnalyticsDevice(userAgent);

  if (device === "bot") {
    return mahoonAnalyticsJson({ ok: true, skipped: true });
  }

  if (pathname.startsWith("/admin")) {
    return mahoonAnalyticsJson({ ok: true, skipped: true });
  }

  const cf = request.cf || {};

  await env.DB.prepare(
    [
      "INSERT INTO analytics_events",
      "(event_type, path, url, title, referrer, referrer_host, visitor_id, session_id, post_slug, tag, device, country, city, user_agent, screen_width, screen_height, language)",
      "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    ].join(" ")
  )
    .bind(
      eventType,
      pathname,
      url,
      title,
      referrer,
      referrerHost,
      mahoonAnalyticsCleanText(body.visitor_id || "", 120),
      mahoonAnalyticsCleanText(body.session_id || "", 120),
      mahoonAnalyticsPostSlug(pathname),
      mahoonAnalyticsTag(pathname),
      device,
      mahoonAnalyticsCleanText(cf.country || "", 80),
      mahoonAnalyticsCleanText(cf.city || "", 160),
      userAgent,
      Number(body.screen_width || 0) || null,
      Number(body.screen_height || 0) || null,
      mahoonAnalyticsCleanText(body.language || "", 40)
    )
    .run();

  return mahoonAnalyticsJson({ ok: true });
}

async function mahoonGetAnalytics(request, env) {
  if (!mahoonAnalyticsIsAdmin(request, env)) {
    return mahoonAnalyticsJson({ ok: false, error: "Unauthorized" }, 401);
  }

  if (!env.DB) {
    return mahoonAnalyticsJson({ ok: false, error: "DB binding is missing" }, 500);
  }

  const url = new URL(request.url);
    // mahoon-ios-media-top-priority-v1
    if (
      (request.method === "GET" || request.method === "HEAD" || request.method === "OPTIONS") &&
      (url.pathname === "/media" || url.pathname.startsWith("/media/"))
    ) {
      return handleMahooonIosCompatibleMedia(request, env, url);
    }
    // end-mahoon-ios-media-top-priority-v1
    // mahoon-ios-media-range-v2-route
    if (url.pathname === "/media" || url.pathname.startsWith("/media/")) {
      return handleMahooonIosCompatibleMedia(request, env, url);
    }
    // end-mahoon-ios-media-range-v2-route

    // mahoon-analytics-report-route-v3
    if ((url.pathname === "/analytics/report" || url.pathname === "/analytics/admin") && request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: mahoonAnalyticsCorsHeaders() });
    }

    if ((url.pathname === "/analytics/report" || url.pathname === "/analytics/admin") && request.method === "GET") {
      return mahoonGetAnalytics(request, env);
    }


    // mahoon-analytics-routes-v2
    if ((url.pathname === "/analytics/track" || url.pathname === "/admin/analytics") && request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: mahoonAnalyticsCorsHeaders() });
    }

    if (url.pathname === "/analytics/track" && request.method === "POST") {
      return mahoonTrackAnalytics(request, env);
    }

    if (url.pathname === "/admin/analytics" && request.method === "GET") {
      return mahoonGetAnalytics(request, env);
    }

  const rawDays = Number(url.searchParams.get("days") || "30");
  const days = Math.max(1, Math.min(365, Number.isFinite(rawDays) ? rawDays : 30));
  const since = new Date(Date.now() - days * 86400000).toISOString().slice(0, 19).replace("T", " ");

  const totals = await env.DB.prepare(
    [
      "SELECT",
      "COUNT(*) AS pageviews,",
      "COUNT(DISTINCT NULLIF(visitor_id, '')) AS unique_visitors,",
      "COUNT(DISTINCT NULLIF(session_id, '')) AS sessions",
      "FROM analytics_events",
      "WHERE created_at >= ?"
    ].join(" ")
  ).bind(since).first();

  const today = await env.DB.prepare(
    "SELECT COUNT(*) AS pageviews FROM analytics_events WHERE date(created_at) = date('now')"
  ).first();

  const yesterday = await env.DB.prepare(
    "SELECT COUNT(*) AS pageviews FROM analytics_events WHERE date(created_at) = date('now', '-1 day')"
  ).first();

  const topPages = await env.DB.prepare(
    [
      "SELECT path, COALESCE(NULLIF(title, ''), path) AS title,",
      "COUNT(*) AS views,",
      "COUNT(DISTINCT NULLIF(visitor_id, '')) AS visitors",
      "FROM analytics_events",
      "WHERE created_at >= ?",
      "GROUP BY path, title",
      "ORDER BY views DESC",
      "LIMIT 20"
    ].join(" ")
  ).bind(since).all();

  const byDay = await env.DB.prepare(
    [
      "SELECT date(created_at) AS day,",
      "COUNT(*) AS views,",
      "COUNT(DISTINCT NULLIF(visitor_id, '')) AS visitors",
      "FROM analytics_events",
      "WHERE created_at >= ?",
      "GROUP BY day",
      "ORDER BY day ASC"
    ].join(" ")
  ).bind(since).all();

  const referrers = await env.DB.prepare(
    [
      "SELECT COALESCE(NULLIF(referrer_host, ''), 'Direct') AS source,",
      "COUNT(*) AS views",
      "FROM analytics_events",
      "WHERE created_at >= ?",
      "GROUP BY source",
      "ORDER BY views DESC",
      "LIMIT 15"
    ].join(" ")
  ).bind(since).all();

  const devices = await env.DB.prepare(
    [
      "SELECT COALESCE(NULLIF(device, ''), 'unknown') AS device,",
      "COUNT(*) AS views",
      "FROM analytics_events",
      "WHERE created_at >= ?",
      "GROUP BY device",
      "ORDER BY views DESC"
    ].join(" ")
  ).bind(since).all();

  const countries = await env.DB.prepare(
    [
      "SELECT COALESCE(NULLIF(country, ''), 'unknown') AS country,",
      "COUNT(*) AS views",
      "FROM analytics_events",
      "WHERE created_at >= ?",
      "GROUP BY country",
      "ORDER BY views DESC",
      "LIMIT 15"
    ].join(" ")
  ).bind(since).all();

  const recent = await env.DB.prepare(
    [
      "SELECT path, title, device, country, referrer_host, created_at",
      "FROM analytics_events",
      "WHERE created_at >= ?",
      "ORDER BY datetime(created_at) DESC, id DESC",
      "LIMIT 25"
    ].join(" ")
  ).bind(since).all();

  return mahoonAnalyticsJson({
    ok: true,
    days,
    since,
    totals: {
      pageviews: Number(totals?.pageviews || 0),
      unique_visitors: Number(totals?.unique_visitors || 0),
      sessions: Number(totals?.sessions || 0),
      today: Number(today?.pageviews || 0),
      yesterday: Number(yesterday?.pageviews || 0)
    },
    topPages: topPages.results || [],
    byDay: byDay.results || [],
    referrers: referrers.results || [],
    devices: devices.results || [],
    countries: countries.results || [],
    recent: recent.results || []
  });
}


/* mahoon-analytics-v5 */
function mahoonAnalyticsCorsHeadersV5() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Admin-Token",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS"
  };
}

function mahoonAnalyticsJsonV5(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      ...mahoonAnalyticsCorsHeadersV5(),
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store"
    }
  });
}

function mahoonAnalyticsTextV5(value, maxLength = 500) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, maxLength);
}

function mahoonAnalyticsPathV5(value) {
  const source = String(value || "/").trim();
  if (!source || !source.startsWith("/")) return "/";
  return source.slice(0, 400);
}

function mahoonAnalyticsHostV5(value) {
  try {
    const host = new URL(String(value || "")).hostname || "";
    return host.replace(/^www\./i, "").slice(0, 160);
  } catch {
    return "";
  }
}

function mahoonAnalyticsDeviceV5(userAgent) {
  const ua = String(userAgent || "").toLowerCase();

  if (/bot|crawl|spider|slurp|facebookexternalhit|telegrambot|whatsapp|preview/.test(ua)) {
    return "bot";
  }

  if (/tablet|ipad/.test(ua)) return "tablet";
  if (/mobile|android|iphone|ipod/.test(ua)) return "mobile";

  return "desktop";
}

function mahoonAnalyticsPostSlugV5(pathname) {
  const match = String(pathname || "").match(/^\/post\/(.+)$/);
  if (!match) return "";

  try {
    return decodeURIComponent(match[1]).slice(0, 500);
  } catch {
    return match[1].slice(0, 500);
  }
}

function mahoonAnalyticsTagV5(pathname) {
  const match = String(pathname || "").match(/^\/tag\/(.+)$/);
  if (!match) return "";

  try {
    return decodeURIComponent(match[1]).slice(0, 300);
  } catch {
    return match[1].slice(0, 300);
  }
}

function mahoonAnalyticsAdminTokenV5(request) {
  const direct = request.headers.get("X-Admin-Token") || "";
  const authorization = request.headers.get("Authorization") || "";
  const bearer = authorization.toLowerCase().startsWith("bearer ")
    ? authorization.slice(7).trim()
    : "";

  return direct || bearer;
}

function mahoonAnalyticsIsAdminV5(request, env) {
  const expected = String(env.ADMIN_TOKEN || "").trim();
  const received = String(mahoonAnalyticsAdminTokenV5(request) || "").trim();

  return Boolean(expected && received && expected === received);
}

async function mahoonAnalyticsBodyV5(request) {
  const raw = await request.text();

  if (!raw) return {};

  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

async function mahoonTrackAnalyticsV5(request, env) {
  try {
    if (!env.DB) {
      return mahoonAnalyticsJsonV5({ ok: false, error: "DB binding is missing", version: "v5" }, 500);
    }

    const body = await mahoonAnalyticsBodyV5(request);

    const pathname = mahoonAnalyticsPathV5(body.path || "/");
    const userAgent = mahoonAnalyticsTextV5(request.headers.get("User-Agent") || "", 700);
    const device = mahoonAnalyticsDeviceV5(userAgent);

    if (device === "bot") {
      return mahoonAnalyticsJsonV5({ ok: true, saved: false, skipped: true, reason: "bot", version: "v5" });
    }

    if (pathname.startsWith("/admin")) {
      return mahoonAnalyticsJsonV5({ ok: true, saved: false, skipped: true, reason: "admin", version: "v5" });
    }

    const referrer = mahoonAnalyticsTextV5(body.referrer || "", 900);
    const cf = request.cf || {};

    await env.DB.prepare(
      [
        "INSERT INTO analytics_events",
        "(event_type, path, url, title, referrer, referrer_host, visitor_id, session_id, post_slug, tag, device, country, city, user_agent, screen_width, screen_height, language)",
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
      ].join(" ")
    )
      .bind(
        mahoonAnalyticsTextV5(body.event_type || "page_view", 40) || "page_view",
        pathname,
        mahoonAnalyticsTextV5(body.url || "", 900),
        mahoonAnalyticsTextV5(body.title || "", 240),
        referrer,
        mahoonAnalyticsHostV5(referrer),
        mahoonAnalyticsTextV5(body.visitor_id || "", 120),
        mahoonAnalyticsTextV5(body.session_id || "", 120),
        mahoonAnalyticsPostSlugV5(pathname),
        mahoonAnalyticsTagV5(pathname),
        device,
        mahoonAnalyticsTextV5(cf.country || "", 80),
        mahoonAnalyticsTextV5(cf.city || "", 160),
        userAgent,
        Number(body.screen_width || 0) || null,
        Number(body.screen_height || 0) || null,
        mahoonAnalyticsTextV5(body.language || "", 40)
      )
      .run();

    return mahoonAnalyticsJsonV5({ ok: true, saved: true, version: "v5", path: pathname });
  } catch (error) {
    return mahoonAnalyticsJsonV5({
      ok: false,
      error: String(error?.message || error),
      version: "v5"
    }, 500);
  }
}

async function mahoonGetAnalyticsV5(request, env) {
  try {
    if (!mahoonAnalyticsIsAdminV5(request, env)) {
      return mahoonAnalyticsJsonV5({ ok: false, error: "Unauthorized", version: "v5" }, 401);
    }

    if (!env.DB) {
      return mahoonAnalyticsJsonV5({ ok: false, error: "DB binding is missing", version: "v5" }, 500);
    }

    const url = new URL(request.url);
    const rawDays = Number(url.searchParams.get("days") || "30");
    const days = Math.max(1, Math.min(365, Number.isFinite(rawDays) ? rawDays : 30));
    const since = new Date(Date.now() - days * 86400000).toISOString().slice(0, 19).replace("T", " ");

    const totals = await env.DB.prepare(
      [
        "SELECT",
        "COUNT(*) AS pageviews,",
        "COUNT(DISTINCT NULLIF(visitor_id, '')) AS unique_visitors,",
        "COUNT(DISTINCT NULLIF(session_id, '')) AS sessions",
        "FROM analytics_events",
        "WHERE created_at >= ?"
      ].join(" ")
    ).bind(since).first();

    const today = await env.DB.prepare(
      "SELECT COUNT(*) AS pageviews FROM analytics_events WHERE date(created_at) = date('now')"
    ).first();

    const yesterday = await env.DB.prepare(
      "SELECT COUNT(*) AS pageviews FROM analytics_events WHERE date(created_at) = date('now', '-1 day')"
    ).first();

    const topPages = await env.DB.prepare(
      [
        "SELECT path, COALESCE(NULLIF(title, ''), path) AS title,",
        "COUNT(*) AS views,",
        "COUNT(DISTINCT NULLIF(visitor_id, '')) AS visitors",
        "FROM analytics_events",
        "WHERE created_at >= ?",
        "GROUP BY path, title",
        "ORDER BY views DESC",
        "LIMIT 20"
      ].join(" ")
    ).bind(since).all();

    const byDay = await env.DB.prepare(
      [
        "SELECT date(created_at) AS day,",
        "COUNT(*) AS views,",
        "COUNT(DISTINCT NULLIF(visitor_id, '')) AS visitors",
        "FROM analytics_events",
        "WHERE created_at >= ?",
        "GROUP BY day",
        "ORDER BY day ASC"
      ].join(" ")
    ).bind(since).all();

    const referrers = await env.DB.prepare(
      [
        "SELECT COALESCE(NULLIF(referrer_host, ''), 'Direct') AS source,",
        "COUNT(*) AS views",
        "FROM analytics_events",
        "WHERE created_at >= ?",
        "GROUP BY source",
        "ORDER BY views DESC",
        "LIMIT 15"
      ].join(" ")
    ).bind(since).all();

    const devices = await env.DB.prepare(
      [
        "SELECT COALESCE(NULLIF(device, ''), 'unknown') AS device,",
        "COUNT(*) AS views",
        "FROM analytics_events",
        "WHERE created_at >= ?",
        "GROUP BY device",
        "ORDER BY views DESC"
      ].join(" ")
    ).bind(since).all();

    const countries = await env.DB.prepare(
      [
        "SELECT COALESCE(NULLIF(country, ''), 'unknown') AS country,",
        "COUNT(*) AS views",
        "FROM analytics_events",
        "WHERE created_at >= ?",
        "GROUP BY country",
        "ORDER BY views DESC",
        "LIMIT 15"
      ].join(" ")
    ).bind(since).all();

    const recent = await env.DB.prepare(
      [
        "SELECT path, title, device, country, referrer_host, created_at",
        "FROM analytics_events",
        "WHERE created_at >= ?",
        "ORDER BY datetime(created_at) DESC, id DESC",
        "LIMIT 25"
      ].join(" ")
    ).bind(since).all();

    return mahoonAnalyticsJsonV5({
      ok: true,
      version: "v5",
      days,
      since,
      totals: {
        pageviews: Number(totals?.pageviews || 0),
        unique_visitors: Number(totals?.unique_visitors || 0),
        sessions: Number(totals?.sessions || 0),
        today: Number(today?.pageviews || 0),
        yesterday: Number(yesterday?.pageviews || 0)
      },
      topPages: topPages.results || [],
      byDay: byDay.results || [],
      referrers: referrers.results || [],
      devices: devices.results || [],
      countries: countries.results || [],
      recent: recent.results || []
    });
  } catch (error) {
    return mahoonAnalyticsJsonV5({
      ok: false,
      error: String(error?.message || error),
      version: "v5"
    }, 500);
  }
}


/* mahoon-telegram-webhook-refresh-v1 */
function mahoonTelegramWebhookCorsV1() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Admin-Token",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS"
  };
}

function mahoonTelegramWebhookJsonV1(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      ...mahoonTelegramWebhookCorsV1(),
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store"
    }
  });
}

function mahoonTelegramWebhookAdminTokenV1(request) {
  const direct = request.headers.get("X-Admin-Token") || "";
  const authorization = request.headers.get("Authorization") || "";
  const bearer = authorization.toLowerCase().startsWith("bearer ")
    ? authorization.slice(7).trim()
    : "";

  return direct || bearer;
}

function mahoonTelegramWebhookIsAdminV1(request, env) {
  const expected = String(env.ADMIN_TOKEN || "").trim();
  const received = String(mahoonTelegramWebhookAdminTokenV1(request) || "").trim();

  return Boolean(expected && received && expected === received);
}

async function mahoonTelegramBotApiV1(env, method, payload = null) {
  const token = String(env.BOT_TOKEN || "").trim();

  if (!token) {
    throw new Error("BOT_TOKEN is missing");
  }

  const response = await fetch("https://api.telegram.org/bot" + token + "/" + method, {
    method: payload ? "POST" : "GET",
    headers: payload ? { "Content-Type": "application/json" } : {},
    body: payload ? JSON.stringify(payload) : undefined
  });

  const data = await response.json().catch(() => null);

  if (!response.ok || !data?.ok) {
    throw new Error(data?.description || "Telegram API request failed");
  }

  return data;
}

function mahoonTelegramPublicWebhookUrlV1(request, currentUrl) {
  const publicOrigin = new URL(request.url).origin;

  try {
    const current = new URL(String(currentUrl || ""));
    return publicOrigin + current.pathname + current.search;
  } catch {
    return publicOrigin + "/telegram";
  }
}

async function mahoonTelegramWebhookInfoV1(request, env) {
  if (!mahoonTelegramWebhookIsAdminV1(request, env)) {
    return mahoonTelegramWebhookJsonV1({ ok: false, error: "Unauthorized" }, 401);
  }

  try {
    const info = await mahoonTelegramBotApiV1(env, "getWebhookInfo");

    return mahoonTelegramWebhookJsonV1({
      ok: true,
      webhook: info.result || null
    });
  } catch (error) {
    return mahoonTelegramWebhookJsonV1({
      ok: false,
      error: String(error?.message || error)
    }, 500);
  }
}

async function mahoonTelegramWebhookRefreshV1(request, env) {
  if (!mahoonTelegramWebhookIsAdminV1(request, env)) {
    return mahoonTelegramWebhookJsonV1({ ok: false, error: "Unauthorized" }, 401);
  }

  try {
    const before = await mahoonTelegramBotApiV1(env, "getWebhookInfo");
    const currentUrl = before?.result?.url || "";
    const nextUrl = mahoonTelegramPublicWebhookUrlV1(request, currentUrl);

    const allowedUpdates = [
      "message",
      "edited_message",
      "channel_post",
      "edited_channel_post"
    ];

    const setResult = await mahoonTelegramBotApiV1(env, "setWebhook", {
      url: nextUrl,
      allowed_updates: allowedUpdates,
      drop_pending_updates: false
    });

    const after = await mahoonTelegramBotApiV1(env, "getWebhookInfo");

    return mahoonTelegramWebhookJsonV1({
      ok: true,
      refreshed: true,
      webhook_url: nextUrl,
      allowed_updates: allowedUpdates,
      telegram_set_result: setResult.result,
      before: before.result || null,
      after: after.result || null
    });
  } catch (error) {
    return mahoonTelegramWebhookJsonV1({
      ok: false,
      error: String(error?.message || error)
    }, 500);
  }
}


/* mahoon-public-posts-full-v1 */
function mahoonPublicPostsFullCorsV1() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Admin-Token",
    "Access-Control-Allow-Methods": "GET, OPTIONS"
  };
}

function mahoonPublicPostsFullJsonV1(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      ...mahoonPublicPostsFullCorsV1(),
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store"
    }
  });
}

async function mahoonPublicPostsFullV1(request, env) {
  try {
    if (!env.DB) {
      return mahoonPublicPostsFullJsonV1({
        ok: false,
        error: "DB binding is missing"
      }, 500);
    }

    const url = new URL(request.url);
    const rawLimit = Number(url.searchParams.get("limit") || "500");
    const safeLimit = Number.isFinite(rawLimit) ? rawLimit : 500;
    const limit = Math.max(1, Math.min(safeLimit, 1000));

    const result = await env.DB.prepare(
      `SELECT *
       FROM posts
       WHERE (is_published = 1 OR is_published IS NULL)
         AND (deleted_at IS NULL OR deleted_at = '')
       ORDER BY created_at DESC, id DESC
       LIMIT ?`
    ).bind(limit).all();

    const posts = Array.isArray(result?.results) ? result.results : [];

    return mahoonPublicPostsFullJsonV1({
      ok: true,
      posts,
      count: posts.length,
      limit
    });
  } catch (error) {
    return mahoonPublicPostsFullJsonV1({
      ok: false,
      error: String(error?.message || error)
    }, 500);
  }
}


/* mahoon-scale-v1 */
const MAHOON_SCALE_AUDIO_BOOK_TAGS_V1 = [
  "کتاب_گویا",
  "کتاب‌گویا",
  "کتابگویا",
  "کتاب_صوتی",
  "کتاب‌صوتی",
  "کتابصوتی"
];

const MAHOON_SCALE_CATEGORY_DEFS_V1 = [
  {
    title: "کتاب",
    aliases: ["کتاب"],
    tags: ["کتاب", ...MAHOON_SCALE_AUDIO_BOOK_TAGS_V1]
  },
  {
    title: "دیالوگ ها",
    aliases: ["دیالوگ ها", "دیالوگ‌ها", "دیالوگ_ها", "دیالوگها", "دیالوگ"],
    tags: ["دیالوگ", "دیالوگ‌ها", "دیالوگ_ها", "دیالوگها"]
  },
  {
    title: "صوتی",
    aliases: ["صوتی", "صدا", "موسیقی"],
    tags: ["صوتی", "صدا", "موسیقی", ...MAHOON_SCALE_AUDIO_BOOK_TAGS_V1]
  },
  {
    title: "شعر و متن",
    aliases: ["شعر و متن", "متن", "متن‌ها", "متن_ها", "متنها", "شعر", "اشعار", "شعرها", "شعر_ها"],
    tags: ["متن", "متن‌ها", "متن_ها", "متنها", "شعر", "اشعار", "شعرها", "شعر_ها"]
  },
  {
    title: "نقاشی",
    aliases: ["نقاشی"],
    tags: ["نقاشی"]
  }
];

function mahoonScaleCorsV1() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Admin-Token",
    "Access-Control-Allow-Methods": "GET, OPTIONS"
  };
}

function mahoonScaleJsonV1(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      ...mahoonScaleCorsV1(),
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=45, stale-while-revalidate=120"
    }
  });
}

function mahoonScaleAdminJsonV1(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      ...mahoonScaleCorsV1(),
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store"
    }
  });
}

function mahoonScaleNormalizeV1(value) {
  return String(value || "")
    .replace(/^#/, "")
    .replace(/[يى]/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/\u200c/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function mahoonScaleCategoryByTitleV1(value) {
  const normalized = mahoonScaleNormalizeV1(value);

  return MAHOON_SCALE_CATEGORY_DEFS_V1.find((category) =>
    category.aliases.some(
      (alias) => mahoonScaleNormalizeV1(alias) === normalized
    )
  ) || null;
}

function mahoonScaleAllCategoryTagsV1() {
  return MAHOON_SCALE_CATEGORY_DEFS_V1.flatMap((category) => category.tags);
}

function mahoonScaleEscapeLikeV1(value) {
  return String(value || "")
    .replace(/!/g, "!!")
    .replace(/%/g, "!%")
    .replace(/_/g, "!_");
}

function mahoonScaleNormalizeSearchTextV2(value) {
  return String(value || "")
    .replace(/[يى]/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/[\u200c\u200f]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function mahoonScaleNormalizeSearchQueryV2(value) {
  return Array.from(
    mahoonScaleNormalizeSearchTextV2(value)
  ).slice(0, 120).join("");
}

function mahoonScaleIsUsefulSearchQueryV2(value) {
  return /[\p{L}\p{N}]/u.test(String(value || ""));
}

function mahoonScaleTagConditionV1(tags) {
  const safeTags = Array.from(new Set((tags || []).filter(Boolean)));

  if (!safeTags.length) {
    return {
      sql: "1 = 0",
      params: []
    };
  }

  const paddedText =
    "(' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ')";

  return {
    sql: "(" + safeTags
      .map(() => paddedText + " LIKE ? ESCAPE '!'")
      .join(" OR ") + ")",
    params: safeTags.map(
      (tag) => "% #" + mahoonScaleEscapeLikeV1(tag) + " %"
    )
  };
}

function mahoonScalePublicBaseWhereV1() {
  const categoryCondition = mahoonScaleTagConditionV1(mahoonScaleAllCategoryTagsV1());

  return {
    sql: [
      "slug IS NOT NULL",
      "slug != ''",
      "(deleted_at IS NULL OR deleted_at = '')",
      "(is_published = 1 OR is_published IS NULL)",
      categoryCondition.sql
    ].join(" AND "),
    params: categoryCondition.params
  };
}

function mahoonScaleBuildPublicWhereV1(url) {
  const base = mahoonScalePublicBaseWhereV1();
  const clauses = [base.sql];
  const params: Array<string | number> = [...base.params];

  const categoryValue = String(url.searchParams.get("category") || "").trim();
  const tagValue = String(url.searchParams.get("tag") || "").replace(/^#/, "").trim();
  const rawQ = String(url.searchParams.get("q") || "");
  const q = mahoonScaleNormalizeSearchQueryV2(rawQ);
  const qRequested = rawQ.trim() !== "";
  const qUseful = mahoonScaleIsUsefulSearchQueryV2(q);

  if (categoryValue) {
    const category = mahoonScaleCategoryByTitleV1(categoryValue);

    if (category) {
      const condition = mahoonScaleTagConditionV1(category.tags);
      clauses.push(condition.sql);
      params.push(...condition.params);
    } else {
      clauses.push("1 = 0");
    }
  }

  if (tagValue) {
    const tagCondition = mahoonScaleTagConditionV1(
      mahoonScaleTagCandidateVariantsV1(tagValue)
    );
    clauses.push(tagCondition.sql);
    params.push(...tagCondition.params);
  }

  if (qRequested && !qUseful) {
    clauses.push("1 = 0");
  } else if (q) {
    const maybeId = /^[0-9]+$/.test(q) ? Number(q) : NaN;

    clauses.push("(" + [
      "INSTR(LOWER(COALESCE(text, '')), ?) > 0",
      "INSTR(LOWER(COALESCE(slug, '')), ?) > 0",
      "INSTR(LOWER(COALESCE(seo_title, '')), ?) > 0",
      "INSTR(LOWER(COALESCE(seo_description, '')), ?) > 0",
      "INSTR(LOWER(COALESCE(media_file_name, '')), ?) > 0",
      Number.isFinite(maybeId) && maybeId > 0 ? "id = ?" : "1 = 0"
    ].join(" OR ") + ")");

    params.push(q, q, q, q, q);

    if (Number.isFinite(maybeId) && maybeId > 0) {
      params.push(maybeId);
    }
  }

  return {
    sql: clauses.join(" AND "),
    params
  };
}

function mahoonScalePublicColumnsV1() {
  return [
    "id",
    "text",
    "slug",
    "created_at",
    "updated_at",
    "is_published",
    "media_type",
    "media_file_id",
    "media_unique_id",
    "media_mime_type",
    "media_file_name",
    "media_duration",
    "media_width",
    "media_height",
    "media_size",
    "photo_file_id",
    "photo_unique_id",
    "photo_width",
    "photo_height",
    "seo_title",
    "seo_description",
    "COALESCE(view_count, 0) AS view_count",
    "last_viewed_at"
  ].join(", ");
}

async function mahoonScalePublicStatsObjectV1(env) {
  const base = mahoonScalePublicBaseWhereV1();

    const statsRow = (await env.DB.prepare(
    `WITH flags AS ( SELECT id, CASE WHEN (slug IS NOT NULL AND slug != '' AND (deleted_at IS NULL OR deleted_at = '') AND (is_published = 1 OR is_published IS NULL) AND ((' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب!_گویا %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب‌گویا %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتابگویا %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب!_صوتی %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب‌صوتی %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتابصوتی %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #دیالوگ %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #دیالوگ‌ها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #دیالوگ!_ها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #دیالوگها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #صوتی %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #صدا %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #موسیقی %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #متن %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #متن‌ها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #متن!_ها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #متنها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #شعر %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #اشعار %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #شعرها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #شعر!_ها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #نقاشی %' ESCAPE '!')) THEN 1 ELSE 0 END AS visible_flag, CASE WHEN ((deleted_at IS NULL OR deleted_at = '') AND COALESCE(is_published, 1) = 1) THEN 1 ELSE 0 END AS published_flag, CASE WHEN ((deleted_at IS NULL OR deleted_at = '')) THEN 1 ELSE 0 END AS total_flag, CASE WHEN ((deleted_at IS NOT NULL AND deleted_at != '')) THEN 1 ELSE 0 END AS deleted_flag, CASE WHEN ((slug IS NOT NULL AND slug != '' AND (deleted_at IS NULL OR deleted_at = '') AND (is_published = 1 OR is_published IS NULL) AND ((' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب!_گویا %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب‌گویا %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتابگویا %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب!_صوتی %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب‌صوتی %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتابصوتی %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #دیالوگ %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #دیالوگ‌ها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #دیالوگ!_ها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #دیالوگها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #صوتی %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #صدا %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #موسیقی %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #متن %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #متن‌ها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #متن!_ها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #متنها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #شعر %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #اشعار %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #شعرها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #شعر!_ها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #نقاشی %' ESCAPE '!')) AND COALESCE(media_type, '') = '' AND COALESCE(media_file_id, '') = '' AND COALESCE(photo_file_id, '') = '') THEN 1 ELSE 0 END AS text_flag, CASE WHEN (((' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب!_گویا %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب‌گویا %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتابگویا %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب!_صوتی %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب‌صوتی %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتابصوتی %' ESCAPE '!')) THEN 1 ELSE 0 END AS category_0_flag, CASE WHEN (((' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #دیالوگ %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #دیالوگ‌ها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #دیالوگ!_ها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #دیالوگها %' ESCAPE '!')) THEN 1 ELSE 0 END AS category_1_flag, CASE WHEN (((' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #صوتی %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #صدا %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #موسیقی %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب!_گویا %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب‌گویا %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتابگویا %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب!_صوتی %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتاب‌صوتی %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #کتابصوتی %' ESCAPE '!')) THEN 1 ELSE 0 END AS category_2_flag, CASE WHEN (((' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #متن %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #متن‌ها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #متن!_ها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #متنها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #شعر %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #اشعار %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #شعرها %' ESCAPE '!' OR (' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #شعر!_ها %' ESCAPE '!')) THEN 1 ELSE 0 END AS category_3_flag, CASE WHEN (((' ' || replace(replace(replace(COALESCE(text, ''), char(13), ' '), char(10), ' '), char(9), ' ') || ' ') LIKE '% #نقاشی %' ESCAPE '!')) THEN 1 ELSE 0 END AS category_4_flag FROM posts ) SELECT COALESCE(SUM(visible_flag), 0) AS visible_posts, MAX(CASE WHEN visible_flag = 1 THEN id ELSE NULL END) AS latest_id, COALESCE(SUM(published_flag), 0) AS published_posts, COALESCE(SUM(total_flag), 0) AS total_posts, COALESCE(SUM(deleted_flag), 0) AS deleted_posts, COALESCE(SUM(text_flag), 0) AS text_posts, COALESCE(SUM(CASE WHEN visible_flag = 1 AND category_0_flag = 1 THEN 1 ELSE 0 END), 0) AS category_0, COALESCE(SUM(CASE WHEN visible_flag = 1 AND category_1_flag = 1 THEN 1 ELSE 0 END), 0) AS category_1, COALESCE(SUM(CASE WHEN visible_flag = 1 AND category_2_flag = 1 THEN 1 ELSE 0 END), 0) AS category_2, COALESCE(SUM(CASE WHEN visible_flag = 1 AND category_3_flag = 1 THEN 1 ELSE 0 END), 0) AS category_3, COALESCE(SUM(CASE WHEN visible_flag = 1 AND category_4_flag = 1 THEN 1 ELSE 0 END), 0) AS category_4 FROM flags`
  ).first()) as Record<string, number | null> | null;

  

  

  

  

    const categoryConditions = MAHOON_SCALE_CATEGORY_DEFS_V1.map((category, index) => ({
    category,
    alias: "category_" + index,
    condition: mahoonScaleTagConditionV1(category.tags)
  }));

  const categorySelects = categoryConditions.map(({ alias, condition }) =>
    `COALESCE(SUM(CASE WHEN ${condition.sql} THEN 1 ELSE 0 END), 0) AS ${alias}`
  );

  const categoryParams = categoryConditions.flatMap(({ condition }) =>
    condition.params
  );

  

  const categoryValues =
    (statsRow || {}) as Record<string, unknown>;

  const categoryCounts = categoryConditions.map(({ category, alias }) => ({
    title: category.title,
    count: Number(categoryValues[alias] || 0)
  }));

  const categoryMap = Object.fromEntries(
    categoryCounts.map(({ title, count }) => [title, count])
  );

  return {
    visible_posts: Number(statsRow?.visible_posts || 0),
    published_posts: Number(statsRow?.published_posts || 0),
    total_posts: Number(statsRow?.total_posts || 0),
    deleted_posts: Number(statsRow?.deleted_posts || 0),
    text_posts: Number(statsRow?.text_posts || 0),
    latest_id: Number(statsRow?.latest_id || 0),
    active_categories: categoryCounts.filter((item) => item.count > 0).length,
    category_counts: categoryCounts,
    category_map: categoryMap
  };
}



// mahoon-public-tag-posts-v1
function mahoonScaleNormalizeExactTagV1(value) {
  return String(value || "")
    .replace(/^#/, "")
    .replace(/[يى]/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/[\u200c\u200f]/g, "")
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function mahoonScaleExtractExactTagsV1(value) {
  return Array.from(String(value || "").matchAll(/(^|\s)#([^\s#]+)/gu))
    .map((match) => mahoonScaleNormalizeExactTagV1(match[2]))
    .filter(Boolean);
}

function mahoonScaleTagCandidateVariantsV1(value) {
  const raw = String(value || "")
    .replace(/^#/, "")
    .trim();
  const spaced = raw
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  return Array.from(new Set([
    raw,
    spaced,
    spaced.replace(/ /g, "_"),
    spaced.replace(/ /g, "\u200c"),
    raw.replace(/[\u200c\u200f]/g, ""),
    spaced.replace(/[\u200c\u200f]/g, "")
  ].map((item) => String(item || "").trim()).filter(Boolean)));
}

function mahoonScaleTagSearchTextV1(post) {
  return mahoonScaleNormalizeSearchTextV2([
    post?.id,
    post?.text,
    post?.slug,
    post?.seo_title,
    post?.seo_description,
    post?.media_file_name
  ].join(" "));
}

async function mahoonScaleSyncPostTagProjectionV1(env, postId, text) {
  const id = Number(postId);

  if (!env.DB || !Number.isInteger(id) || id <= 0) {
    return;
  }

  const tags = [
    ...new Set(
      Array.from(
        mahoonScaleExtractExactTagsV1(text || "")
      ).map(String)
    ),
  ];

  const statements = [
    env.DB.prepare(
      "DELETE FROM mahoon_post_tags_v1 WHERE post_id = ?"
    ).bind(id),
    ...tags.map((tag) =>
      env.DB.prepare(
        "INSERT OR IGNORE INTO mahoon_post_tags_v1(post_id, tag_norm) VALUES (?, ?)"
      ).bind(id, tag)
    ),
  ];

  await env.DB.batch(statements);
}

async function mahoonScalePublicTagPostsV1(request, env, origin) {
  try {
    if (!env.DB) {
      return mahoonScaleJsonV1({ ok: false, error: "DB binding is missing" }, 500);
    }

    const url = new URL(request.url);
    const tag = String(url.searchParams.get("tag") || "").replace(/^#/, "").trim();
    const normalizedTag = mahoonScaleNormalizeExactTagV1(tag);

    if (!normalizedTag) {
      return mahoonScaleJsonV1({ ok: false, error: "Tag is required" }, 400);
    }

    const rawLimit = Number(url.searchParams.get("limit") || "20");
    const rawOffset = Number(url.searchParams.get("offset") || "0");
    const limit = Math.max(1, Math.min(Number.isFinite(rawLimit) ? rawLimit : 20, 120));
    const offset = Math.max(0, Number.isFinite(rawOffset) ? rawOffset : 0);
    const q = mahoonScaleNormalizeExactTagV1(url.searchParams.get("q") || "");
    const base = mahoonScalePublicBaseWhereV1();
    const variants = mahoonScaleTagCandidateVariantsV1(tag);
    const candidateSql = variants.map(() => "p.text LIKE ?").join(" OR ");
    const candidateParams = variants.map((variant) => "%#" + variant + "%");

    const result = await env.DB.prepare(
      [
        "SELECT " + mahoonScalePublicColumnsV1(),
        "FROM mahoon_post_tags_v1 AS t",
        "JOIN posts AS p ON p.id = t.post_id",
        "WHERE t.tag_norm = ?",
        "AND " + base.sql,
        "AND (" + candidateSql + ")",
        "ORDER BY created_at DESC, id DESC"
      ].join(" ")
    ).bind(normalizedTag, ...base.params, ...candidateParams).all();

    const candidates = Array.isArray(result?.results) ? result.results : [];
    const exact = candidates.filter((post) => {
      const tags = mahoonScaleExtractExactTagsV1(post?.text);
      if (!tags.includes(normalizedTag)) return false;
      if (!q) return true;
      return mahoonScaleTagSearchTextV1(post).includes(q);
    });
    const total = exact.length;
    const page = exact.slice(offset, offset + limit);
    const nextOffset = offset + page.length;

    return mahoonScaleJsonV1({
      ok: true,
      mode: "tag",
      tag,
      posts: page.map((post) => postWithMediaUrl(post, origin)),
      total,
      limit,
      offset,
      next_offset: nextOffset,
      has_more: nextOffset < total
    });
  } catch (error) {
    return mahoonScaleJsonV1({ ok: false, error: String(error?.message || error) }, 500);
  }
}
// end-mahoon-public-tag-posts-v1

async function mahoonScalePublicHomeV1(request, env, origin) {
  try {
    if (!env.DB) {
      return mahoonScaleJsonV1({ ok: false, error: "DB binding is missing" }, 500);
    }

    const url = new URL(request.url);
    const rawLimit = Number(url.searchParams.get("limit") || "80");
    const limit = Math.max(1, Math.min(Number.isFinite(rawLimit) ? rawLimit : 80, 120));
    const base = mahoonScalePublicBaseWhereV1();

    const stats = await mahoonScalePublicStatsObjectV1(env);

    const result = await env.DB.prepare(
      [
        "SELECT " + mahoonScalePublicColumnsV1(),
        "FROM posts INDEXED BY idx_posts_public_created_id",
        "WHERE " + base.sql,
        "ORDER BY created_at DESC, id DESC",
        "LIMIT ?"
      ].join(" ")
    ).bind(...base.params, limit).all();

    const posts = Array.isArray(result?.results) ? result.results : [];

    return mahoonScaleJsonV1({
      ok: true,
      mode: "home",
      stats,
      posts: posts.map((post) => postWithMediaUrl(post, origin))
    });
  } catch (error) {
    return mahoonScaleJsonV1({ ok: false, error: String(error?.message || error) }, 500);
  }
}

async function mahoonScalePublicPostsV1(request, env, origin) {
  try {
    if (!env.DB) {
      return mahoonScaleJsonV1({ ok: false, error: "DB binding is missing" }, 500);
    }

    const url = new URL(request.url);
    const rawLimit = Number(url.searchParams.get("limit") || "20");
    const rawOffset = Number(url.searchParams.get("offset") || "0");
    const limit = Math.max(1, Math.min(Number.isFinite(rawLimit) ? rawLimit : 20, 120));
    const offset = Math.max(0, Number.isFinite(rawOffset) ? rawOffset : 0);
    const where = mahoonScaleBuildPublicWhereV1(url);

    const envelopeRow = await env.DB.prepare(
      [
        "WITH filtered AS MATERIALIZED (",
        "SELECT " + mahoonScalePublicColumnsV1(),
        "FROM posts",
        "WHERE " + where.sql,
        "), page AS MATERIALIZED (",
        "SELECT \"id\", \"text\", \"slug\", \"created_at\", \"updated_at\", \"is_published\", \"media_type\", \"media_file_id\", \"media_unique_id\", \"media_mime_type\", \"media_file_name\", \"media_duration\", \"media_width\", \"media_height\", \"media_size\", \"photo_file_id\", \"photo_unique_id\", \"photo_width\", \"photo_height\", \"seo_title\", \"seo_description\", \"view_count\", \"last_viewed_at\"",
        "FROM filtered",
        "ORDER BY created_at DESC, id DESC",
        "LIMIT ? OFFSET ?",
        ")",
        "SELECT",
        "json_object('total', (SELECT COUNT(*) FROM filtered), 'posts', json(COALESCE((SELECT json_group_array(json_object('id', ordered_page.\"id\", 'text', ordered_page.\"text\", 'slug', ordered_page.\"slug\", 'created_at', ordered_page.\"created_at\", 'updated_at', ordered_page.\"updated_at\", 'is_published', ordered_page.\"is_published\", 'media_type', ordered_page.\"media_type\", 'media_file_id', ordered_page.\"media_file_id\", 'media_unique_id', ordered_page.\"media_unique_id\", 'media_mime_type', ordered_page.\"media_mime_type\", 'media_file_name', ordered_page.\"media_file_name\", 'media_duration', ordered_page.\"media_duration\", 'media_width', ordered_page.\"media_width\", 'media_height', ordered_page.\"media_height\", 'media_size', ordered_page.\"media_size\", 'photo_file_id', ordered_page.\"photo_file_id\", 'photo_unique_id', ordered_page.\"photo_unique_id\", 'photo_width', ordered_page.\"photo_width\", 'photo_height', ordered_page.\"photo_height\", 'seo_title', ordered_page.\"seo_title\", 'seo_description', ordered_page.\"seo_description\", 'view_count', ordered_page.\"view_count\", 'last_viewed_at', ordered_page.\"last_viewed_at\")) FROM (SELECT * FROM page ORDER BY created_at DESC, id DESC) AS ordered_page), json('[]')))) AS payload",
      ].join(" ")
    ).bind(...where.params, limit, offset).first();

    const rawEnvelope =
      envelopeRow && typeof envelopeRow === "object"
        ? Object.values(envelopeRow as Record<string, unknown>)[0]
        : null;

    const envelope =
      rawEnvelope && typeof rawEnvelope === "object" && !Array.isArray(rawEnvelope)
        ? rawEnvelope as { total?: unknown; posts?: unknown }
        : typeof rawEnvelope === "string"
          ? JSON.parse(rawEnvelope) as { total?: unknown; posts?: unknown }
          : null;

    if (!envelope) {
      throw new Error("Public posts single-scan envelope is missing.");
    }

    const total = Number(envelope.total || 0);
    const posts = Array.isArray(envelope.posts) ? envelope.posts : [];

    if (!Number.isFinite(total) || total < 0) {
      throw new Error("Public posts single-scan total is invalid.");
    }

    return mahoonScaleJsonV1({
      ok: true,
      mode: "archive",
      posts: posts.map((post) => postWithMediaUrl(post, origin)),
      total,
      limit,
      offset,
      next_offset: offset + posts.length,
      has_more: offset + posts.length < total
    });
  } catch (error) {
    return mahoonScaleJsonV1({ ok: false, error: String(error?.message || error) }, 500);
  }
}

async function mahoonScaleAdminStatsV1(request, env) {
  try {
    const token = String(request.headers.get("X-Admin-Token") || request.headers.get("Authorization") || "")
      .replace(/^Bearer\s+/i, "")
      .trim();

    if (!env.ADMIN_TOKEN || token !== String(env.ADMIN_TOKEN).trim()) {
      return mahoonScaleAdminJsonV1({ ok: false, error: "Unauthorized" }, 401);
    }

    if (!env.DB) {
      return mahoonScaleAdminJsonV1({ ok: false, error: "DB binding is missing" }, 500);
    }

    const row = await env.DB.prepare(
      [
        "SELECT",
        "COUNT(CASE WHEN (deleted_at IS NULL OR deleted_at = '') THEN 1 END) AS total_posts,",
        "COUNT(CASE WHEN (deleted_at IS NULL OR deleted_at = '') AND COALESCE(is_published, 1) = 1 THEN 1 END) AS published_posts,",
        "COUNT(CASE WHEN (deleted_at IS NULL OR deleted_at = '') AND COALESCE(is_published, 1) != 1 THEN 1 END) AS draft_posts,",
        "COUNT(CASE WHEN deleted_at IS NOT NULL AND deleted_at != '' THEN 1 END) AS deleted_posts,",
        "COUNT(CASE WHEN (deleted_at IS NULL OR deleted_at = '') AND (COALESCE(media_file_id, '') != '' OR COALESCE(photo_file_id, '') != '') THEN 1 END) AS media_posts,",
        "COUNT(CASE WHEN (deleted_at IS NULL OR deleted_at = '') AND COALESCE(media_file_id, '') = '' AND COALESCE(photo_file_id, '') = '' THEN 1 END) AS text_posts,",
        "MAX(CASE WHEN (deleted_at IS NULL OR deleted_at = '') THEN id END) AS latest_id",
        "FROM posts"
      ].join(" ")
    ).first();

    return mahoonScaleAdminJsonV1({
      ok: true,
      stats: {
        total_posts: Number(row?.total_posts || 0),
        published_posts: Number(row?.published_posts || 0),
        draft_posts: Number(row?.draft_posts || 0),
        deleted_posts: Number(row?.deleted_posts || 0),
        media_posts: Number(row?.media_posts || 0),
        text_posts: Number(row?.text_posts || 0),
        latest_id: Number(row?.latest_id || 0)
      }
    });
  } catch (error) {
    return mahoonScaleAdminJsonV1({ ok: false, error: String(error?.message || error) }, 500);
  }
}
/* end-mahoon-scale-v1 */


// mahoon-ios-media-range-v2-helper
function mahoonGuessMimeFromTelegramPath(filePath) {
  const lower = String(filePath || "").toLowerCase();

  if (lower.endsWith(".mp3")) return "audio/mpeg";
  if (lower.endsWith(".m4a")) return "audio/mp4";
  if (lower.endsWith(".aac")) return "audio/aac";
  if (lower.endsWith(".wav")) return "audio/wav";
  if (lower.endsWith(".ogg") || lower.endsWith(".oga") || lower.endsWith(".opus")) return "audio/ogg";

  if (lower.endsWith(".mp4") || lower.endsWith(".m4v")) return "video/mp4";
  if (lower.endsWith(".mov")) return "video/quicktime";
  if (lower.endsWith(".webm")) return "video/webm";

  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
  if (lower.endsWith(".png")) return "image/png";
  if (lower.endsWith(".webp")) return "image/webp";
  if (lower.endsWith(".gif")) return "image/gif";

  return "application/octet-stream";
}

function mahoonEncodeTelegramPath(filePath) {
  return String(filePath || "")
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
}

function mahoonMediaHeaders() {
  const headers = new Headers();

  headers.set("Access-Control-Allow-Origin", "*");
  headers.set("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS");
  headers.set("Access-Control-Allow-Headers", "Range, If-Range, Content-Type, Accept");
  headers.set("Access-Control-Expose-Headers", "Accept-Ranges, Content-Length, Content-Range, Content-Type, ETag, Last-Modified");
  headers.set("Accept-Ranges", "bytes");

  return headers;
}

function mahoonCopyHeader(toHeaders, fromHeaders, name) {
  const value = fromHeaders.get(name);

  if (value) {
    toHeaders.set(name, value);
  }
}

function mahoonParseRange(rangeHeader, totalSize) {
  const source = String(rangeHeader || "").trim();

  if (!source || !source.toLowerCase().startsWith("bytes=")) return null;
  if (!Number.isFinite(totalSize) || totalSize <= 0) return null;

  const rangeText = source.replace(/^bytes=/i, "").split(",")[0].trim();
  const parts = rangeText.split("-");

  if (parts.length !== 2) return null;

  const startText = parts[0].trim();
  const endText = parts[1].trim();

  let start = 0;
  let end = totalSize - 1;

  if (!startText && endText) {
    const suffix = Number(endText);
    if (!Number.isFinite(suffix) || suffix <= 0) return null;

    start = Math.max(totalSize - suffix, 0);
    end = totalSize - 1;
  } else {
    start = Number(startText);
    end = endText ? Number(endText) : totalSize - 1;

    if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  }

  start = Math.max(0, Math.floor(start));
  end = Math.min(totalSize - 1, Math.floor(end));

  if (start > end || start >= totalSize) return null;

  return { start, end };
}

function mahoonRange416(totalSize, contentType) {
  const headers = mahoonMediaHeaders();

  headers.set("Content-Type", contentType || "application/octet-stream");
  headers.set("Content-Range", "bytes */" + String(Math.max(0, totalSize || 0)));

  return new Response(null, {
    status: 416,
    headers
  });
}

async function handleMahooonIosCompatibleMedia(request, env, url) {
  if (request.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: mahoonMediaHeaders()
    });
  }

  if (request.method !== "GET" && request.method !== "HEAD") {
    return new Response("Method Not Allowed", {
      status: 405,
      headers: mahoonMediaHeaders()
    });
  }

  const fromPath = url.pathname.startsWith("/media/")
    ? url.pathname.slice("/media/".length)
    : "";

  const fileId = decodeURIComponent(fromPath || url.searchParams.get("file_id") || "").trim();

  if (!fileId) {
    return new Response("Missing media file id", {
      status: 400,
      headers: mahoonMediaHeaders()
    });
  }

  const botToken = String(env.BOT_TOKEN || "").trim();

  if (!botToken) {
    return new Response("BOT_TOKEN is not configured", {
      status: 500,
      headers: mahoonMediaHeaders()
    });
  }

  const telegramInfoUrl = "https://api.telegram.org/bot" + botToken + "/getFile?file_id=" + encodeURIComponent(fileId);
  const infoRes = await fetch(telegramInfoUrl, {
    headers: {
      Accept: "application/json"
    }
  });

  const info = await infoRes.json().catch(() => null);
  const filePath = String(info && info.result && info.result.file_path ? info.result.file_path : "").trim();
  const fileSize = Number(info && info.result && info.result.file_size ? info.result.file_size : 0);

  if (!infoRes.ok || !info || !info.ok || !filePath) {
    const headers = mahoonMediaHeaders();
    headers.set("Content-Type", "text/plain; charset=utf-8");

    return new Response("Telegram file was not found", {
      status: 404,
      headers
    });
  }

  // mahoon-ios-head-response-v1
  if (request.method === "HEAD") {
    const guessedHeadType = mahoonGuessMimeFromTelegramPath(filePath);
    const headContentType = String(fileId || "").startsWith("BAAC")
      ? "video/mp4"
      : String(fileId || "").startsWith("CQAC")
        ? "audio/mpeg"
        : guessedHeadType;

    const headers = mahoonMediaHeaders();

    headers.set("Content-Type", headContentType);
    headers.set("Content-Disposition", "inline");
    headers.set("Cache-Control", "public, max-age=31536000, immutable");

    if (fileSize > 0) {
      const rangeHeaderForHead = request.headers.get("Range");
      const headRange = mahoonParseRange(rangeHeaderForHead, fileSize);

      if (rangeHeaderForHead && !headRange) {
        return mahoonRange416(fileSize, headContentType);
      }

      if (headRange) {
        headers.set("Content-Range", "bytes " + headRange.start + "-" + headRange.end + "/" + fileSize);
        headers.set("Content-Length", String(headRange.end - headRange.start + 1));

        return new Response(null, {
          status: 206,
          headers
        });
      }

      headers.set("Content-Length", String(fileSize));
    }

    return new Response(null, {
      status: 200,
      headers
    });
  }
  // end-mahoon-ios-head-response-v1

  const fileUrl = "https://api.telegram.org/file/bot" + botToken + "/" + mahoonEncodeTelegramPath(filePath);
  const rangeHeader = request.headers.get("Range");
  const ifRangeHeader = request.headers.get("If-Range");

  const upstreamHeaders = new Headers();

  if (rangeHeader) upstreamHeaders.set("Range", rangeHeader);
  if (ifRangeHeader) upstreamHeaders.set("If-Range", ifRangeHeader);

  const upstream = await fetch(fileUrl, {
    method: request.method === "HEAD" ? "HEAD" : "GET",
    headers: upstreamHeaders
  });

  const guessedType = mahoonGuessMimeFromTelegramPath(filePath);
  const iosFallbackType = String(fileId || "").startsWith("BAAC")
    ? "video/mp4"
    : String(fileId || "").startsWith("CQAC")
      ? "audio/mpeg"
      : guessedType;
  const upstreamType = upstream.headers.get("Content-Type") || "";
  const contentType = !upstreamType || /application\/octet-stream/i.test(upstreamType)
    ? iosFallbackType
    : upstreamType;

  const headers = mahoonMediaHeaders();

  headers.set("Content-Type", contentType);
  headers.set("Content-Disposition", "inline");
  headers.set("Cache-Control", "public, max-age=31536000, immutable");

  mahoonCopyHeader(headers, upstream.headers, "Content-Length");
  mahoonCopyHeader(headers, upstream.headers, "Content-Range");
  mahoonCopyHeader(headers, upstream.headers, "ETag");
  mahoonCopyHeader(headers, upstream.headers, "Last-Modified");

  if (!headers.has("Content-Length") && fileSize > 0 && upstream.status !== 206) {
    headers.set("Content-Length", String(fileSize));
  }

  if (upstream.status === 206) {
    return new Response(request.method === "HEAD" ? null : upstream.body, {
      status: 206,
      headers
    });
  }

  if (!upstream.ok) {
    headers.set("Content-Type", "text/plain; charset=utf-8");

    return new Response("Telegram media fetch failed", {
      status: upstream.status || 502,
      headers
    });
  }

  if (rangeHeader && request.method === "HEAD") {
    const totalSize = fileSize || Number(upstream.headers.get("Content-Length") || 0);
    const range = mahoonParseRange(rangeHeader, totalSize);

    if (!range) {
      return mahoonRange416(totalSize, contentType);
    }

    headers.set("Content-Range", "bytes " + range.start + "-" + range.end + "/" + totalSize);
    headers.set("Content-Length", String(range.end - range.start + 1));

    return new Response(null, {
      status: 206,
      headers
    });
  }

  if (rangeHeader && request.method === "GET") {
    const buffer = await upstream.arrayBuffer();
    const totalSize = buffer.byteLength || fileSize || 0;
    const range = mahoonParseRange(rangeHeader, totalSize);

    if (!range) {
      return mahoonRange416(totalSize, contentType);
    }

    const chunk = buffer.slice(range.start, range.end + 1);

    headers.set("Content-Range", "bytes " + range.start + "-" + range.end + "/" + totalSize);
    headers.set("Content-Length", String(chunk.byteLength));

    return new Response(chunk, {
      status: 206,
      headers
    });
  }

  return new Response(request.method === "HEAD" ? null : upstream.body, {
    status: 200,
    headers
  });
}
// end-mahoon-ios-media-range-v2-helper

export default {
  async fetch(request, env) {
    const url = new URL(request.url);


    // mahoon-scale-routes-v1
    if (url.pathname === "/public/home-v1" && request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: mahoonScaleCorsV1() });
    }

    if (url.pathname === "/public/posts-v1" && request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: mahoonScaleCorsV1() });
    }

    if (url.pathname === "/public/tag-posts-v1" && request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: mahoonScaleCorsV1() });
    }

    if (url.pathname === "/public/stats-v1" && request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: mahoonScaleCorsV1() });
    }

    if (url.pathname === "/admin/stats-v1" && request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: mahoonScaleCorsV1() });
    }

    if (url.pathname === "/public/home-v1" && request.method === "GET") {
      return mahoonScalePublicHomeV1(request, env, url.origin);
    }

    if (url.pathname === "/public/posts-v1" && request.method === "GET") {
      return mahoonScalePublicPostsV1(request, env, url.origin);
    }

    if (url.pathname === "/public/tag-posts-v1" && request.method === "GET") {
      return mahoonScalePublicTagPostsV1(request, env, url.origin);
    }

    if (url.pathname === "/public/stats-v1" && request.method === "GET") {
      return mahoonScaleJsonV1({ ok: true, stats: await mahoonScalePublicStatsObjectV1(env) });
    }

    if (url.pathname === "/admin/stats-v1" && request.method === "GET") {
      return mahoonScaleAdminStatsV1(request, env);
    }

    // mahoon-public-posts-full-routes-v1
    if (url.pathname === "/posts-full-public-v1" && request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: mahoonPublicPostsFullCorsV1() });
    }

    if (url.pathname === "/posts-full-public-v1" && request.method === "GET") {
      return mahoonPublicPostsFullV1(request, env);
    }

    // mahoon-telegram-webhook-routes-v1
    if ((url.pathname === "/admin/telegram/webhook-info" || url.pathname === "/admin/telegram/webhook-refresh") && request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: mahoonTelegramWebhookCorsV1() });
    }

    if (url.pathname === "/admin/telegram/webhook-info" && request.method === "GET") {
      return mahoonTelegramWebhookInfoV1(request, env);
    }

    if (url.pathname === "/admin/telegram/webhook-refresh" && request.method === "POST") {
      return mahoonTelegramWebhookRefreshV1(request, env);
    }

    // mahoon-analytics-route-v5
    if (url.pathname === "/analytics/ping-v5" && request.method === "GET") {
      return mahoonAnalyticsJsonV5({ ok: true, service: "mahoon-analytics", version: "v5" });
    }

    if ((url.pathname === "/analytics/collect" || url.pathname === "/analytics/report-v5") && request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: mahoonAnalyticsCorsHeadersV5() });
    }

    if (url.pathname === "/analytics/collect" && request.method === "POST") {
      return mahoonTrackAnalyticsV5(request, env);
    }

    if (url.pathname === "/analytics/report-v5" && request.method === "GET") {
      return mahoonGetAnalyticsV5(request, env);
    }

    // mahoon-analytics-report-route-v4
    if (url.pathname === "/analytics/ping" && request.method === "GET") {
      return mahoonAnalyticsJson({ ok: true, service: "mahoon-analytics", version: "v4" });
    }

    if ((url.pathname === "/analytics/track" || url.pathname === "/analytics/report" || url.pathname === "/analytics/admin") && request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: mahoonAnalyticsCorsHeaders() });
    }

    if (url.pathname === "/analytics/track" && request.method === "POST") {
      return mahoonTrackAnalytics(request, env);
    }

    if ((url.pathname === "/analytics/report" || url.pathname === "/analytics/admin") && request.method === "GET") {
      return mahoonGetAnalytics(request, env);
    }

    const origin = url.origin;

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: CORS_HEADERS
      });
    }

    try {
      if (request.method === "GET" && url.pathname === "/health") {
        return json({
          ok: true,
          service: "tg-cms-api",
          message: "Worker is running"
        });
      }

      if (request.method === "GET" && url.pathname === "/site-settings") {
        const settings = await readSiteSettings(env);

        return json({
          ok: true,
          settings
        });
      }

      if (url.pathname.startsWith("/admin")) {
        if (!requireAdmin(request, env)) {
          return json({
            ok: false,
            error: "Unauthorized"
          }, 401);
        }

        if (request.method === "GET" && url.pathname === "/admin/health") {
          return json({
            ok: true,
            admin: true
          });
        }

        if (request.method === "GET" && url.pathname === "/admin/site-settings") {
          const settings = await readSiteSettings(env);

          return json({
            ok: true,
            settings
          });
        }

        if (request.method === "PATCH" && url.pathname === "/admin/site-settings") {
          const body = await request.json();
          const settings = normalizeSiteSettingsPayload(body);

          try {
            const result = await writeSiteSettings(env, settings);

            return json({
              ok: true,
              saved: true,
              changed: result.changed,
              settings: await readSiteSettings(env)
            });
          } catch (error) {
            if (isMissingSiteSettingsTable(error)) {
              return json({
                ok: false,
                error: "site_settings table is missing. Create the D1 table from the migration file before saving site settings."
              }, 500);
            }

            throw error;
          }
        }

        if (request.method === "POST" && url.pathname === "/admin/upload") {
          const formData = await request.formData();
          const file = formData.get("file");

          if (!file || typeof file.arrayBuffer !== "function") {
            return json({
              ok: false,
              error: "File is required"
            }, 400);
          }

          const media = await uploadAdminFileToTelegram(file, env);

          return json({
            ok: true,
            media: postWithMediaUrl(media, origin)
          });
        }

        // mahoon-admin-posts-api-pagination-v1
        if (request.method === "GET" && url.pathname === "/admin/posts/deleted") {
          const paginationRequested = [
            "limit",
            "offset"
          ].some((key) =>
            url.searchParams.has(key)
          );

          const defaultLimit =
            paginationRequested ? 20 : 100;

          const maxLimit =
            paginationRequested ? 100 : 200;

          const requestedLimit = Number(
            normalizeDigits(
              url.searchParams.get("limit") ||
              String(defaultLimit)
            )
          );

          const requestedOffset = Number(
            normalizeDigits(
              url.searchParams.get("offset") ||
              "0"
            )
          );

          const limit =
            Number.isInteger(requestedLimit) &&
            requestedLimit > 0
              ? Math.min(
                  requestedLimit,
                  maxLimit
                )
              : defaultLimit;

          const offset =
            Number.isInteger(requestedOffset) &&
            requestedOffset >= 0
              ? requestedOffset
              : 0;

          const totalRow = await env.DB.prepare(
            `
            SELECT COUNT(*) AS total
            FROM posts
            WHERE deleted_at IS NOT NULL
            AND deleted_at != ''
            `
          ).first();

          const total = Number(
            totalRow?.total || 0
          );

          const { results } = await env.DB.prepare(
            `
            SELECT
              id,
              text,
              slug,
              created_at,
              updated_at,
              is_published,
              deleted_at,
              media_type,
              media_file_id,
              media_unique_id,
              media_mime_type,
              media_file_name,
              media_duration,
              media_width,
              media_height,
              media_size,
              photo_file_id,
              photo_unique_id,
              photo_width,
              photo_height,
              telegram_message_id,
              chat_id,
              chat_title,
              seo_title,
              seo_description,
              admin_note,
              COALESCE(view_count, 0) AS view_count,
              last_viewed_at
            FROM posts
            WHERE deleted_at IS NOT NULL
            AND deleted_at != ''
            ORDER BY datetime(deleted_at) DESC, id DESC
            LIMIT ? OFFSET ?
            `
          ).bind(
            limit,
            offset
          ).all();

          const posts = Array.isArray(results)
            ? results
            : [];

          return json({
            ok: true,
            mode: paginationRequested
              ? "paged"
              : "legacy",
            posts: posts.map((post) =>
              postWithMediaUrl(post, origin)
            ),
            total,
            limit,
            offset,
            next_offset:
              offset + posts.length,
            has_more:
              offset + posts.length < total
          });
        }

        if (request.method === "GET" && url.pathname === "/admin/posts") {
          const paginationRequested = [
            "limit",
            "offset",
            "q",
            "status",
            "media",
            "sort"
          ].some((key) =>
            url.searchParams.has(key)
          );

          const defaultLimit =
            paginationRequested ? 20 : 500;

          const maxLimit =
            paginationRequested ? 100 : 500;

          const requestedLimit = Number(
            normalizeDigits(
              url.searchParams.get("limit") ||
              String(defaultLimit)
            )
          );

          const requestedOffset = Number(
            normalizeDigits(
              url.searchParams.get("offset") ||
              "0"
            )
          );

          const limit =
            Number.isInteger(requestedLimit) &&
            requestedLimit > 0
              ? Math.min(
                  requestedLimit,
                  maxLimit
                )
              : defaultLimit;

          const offset =
            Number.isInteger(requestedOffset) &&
            requestedOffset >= 0
              ? requestedOffset
              : 0;

          const query = cleanText(
            url.searchParams.get("q") || ""
          ).slice(0, 200);

          const status = cleanText(
            url.searchParams.get("status") ||
            "all"
          ).toLowerCase();

          const media = cleanText(
            url.searchParams.get("media") ||
            "all"
          ).toLowerCase();

          const sort = cleanText(
            url.searchParams.get("sort") ||
            "newest"
          ).toLowerCase();

          const whereParts = [
            "(deleted_at IS NULL OR deleted_at = '')"
          ];

          const whereParams = [];

          if (query) {
            const searchValue =
              "%" + query + "%";

            whereParts.push(
              [
                "(",
                "CAST(id AS TEXT) LIKE ?",
                "OR COALESCE(slug, '') LIKE ?",
                "OR COALESCE(text, '') LIKE ?",
                "OR COALESCE(seo_title, '') LIKE ?",
                "OR COALESCE(seo_description, '') LIKE ?",
                "OR COALESCE(admin_note, '') LIKE ?",
                ")"
              ].join(" ")
            );

            whereParams.push(
              searchValue,
              searchValue,
              searchValue,
              searchValue,
              searchValue,
              searchValue
            );
          }

          if (status === "published") {
            whereParts.push(
              "COALESCE(is_published, 1) = 1"
            );
          } else if (status === "draft") {
            whereParts.push(
              "COALESCE(is_published, 1) != 1"
            );
          }

          if (media === "media") {
            whereParts.push(
              [
                "(",
                "COALESCE(media_file_id, '') != ''",
                "OR COALESCE(photo_file_id, '') != ''",
                ")"
              ].join(" ")
            );
          } else if (media === "photo") {
            whereParts.push(
              [
                "(",
                "COALESCE(media_type, '') = 'photo'",
                "OR COALESCE(photo_file_id, '') != ''",
                ")"
              ].join(" ")
            );
          } else if (media === "video") {
            whereParts.push(
              "COALESCE(media_type, '') IN ('video', 'animation')"
            );
          } else if (media === "audio") {
            whereParts.push(
              "COALESCE(media_type, '') IN ('audio', 'voice')"
            );
          } else if (media === "text") {
            whereParts.push(
              [
                "COALESCE(media_file_id, '') = ''",
                "AND COALESCE(photo_file_id, '') = ''"
              ].join(" ")
            );
          }

          let orderSql =
            "created_at DESC, id DESC";

          if (sort === "oldest") {
            orderSql =
              "created_at ASC, id ASC";
          } else if (sort === "id") {
            orderSql = "id DESC";
          } else if (sort === "title") {
            orderSql = [
              "COALESCE(",
              "NULLIF(seo_title, ''),",
              "NULLIF(slug, ''),",
              "text,",
              "''",
              ") COLLATE NOCASE ASC,",
              "id DESC"
            ].join(" ");
          }

          const whereSql =
            whereParts.join(" AND ");

          const totalStatement =
            env.DB.prepare(
              `
              SELECT COUNT(*) AS total
              FROM posts
              WHERE ${whereSql}
              `
            );

          const totalRow =
            whereParams.length > 0
              ? await totalStatement
                  .bind(...whereParams)
                  .first()
              : await totalStatement.first();

          const total = Number(
            totalRow?.total || 0
          );

          const { results } = await env.DB.prepare(
            `
            SELECT
              id,
              text,
              slug,
              created_at,
              updated_at,
              is_published,
              deleted_at,
              media_type,
              media_file_id,
              media_unique_id,
              media_mime_type,
              media_file_name,
              media_duration,
              media_width,
              media_height,
              media_size,
              photo_file_id,
              photo_unique_id,
              photo_width,
              photo_height,
              telegram_message_id,
              chat_id,
              chat_title,
              seo_title,
              seo_description,
              admin_note,
              COALESCE(view_count, 0) AS view_count,
              last_viewed_at
            FROM posts
            WHERE ${whereSql}
            ORDER BY ${orderSql}
            LIMIT ? OFFSET ?
            `
          ).bind(
            ...whereParams,
            limit,
            offset
          ).all();

          const posts = Array.isArray(results)
            ? results
            : [];

          return json({
            ok: true,
            mode: paginationRequested
              ? "paged"
              : "legacy",
            posts: posts.map((post) =>
              postWithMediaUrl(post, origin)
            ),
            total,
            limit,
            offset,
            next_offset:
              offset + posts.length,
            has_more:
              offset + posts.length < total,
            filters: {
              q: query,
              status,
              media,
              sort
            }
          });
        }

        if (request.method === "POST" && url.pathname === "/admin/posts/bulk") {
          const body = await request.json();
          const ids = normalizeIds(body.ids);
          const action = cleanText(body.action);

          if (ids.length === 0) {
            return json({
              ok: false,
              error: "No post selected"
            }, 400);
          }

          const placeholders = ids.map(() => "?").join(", ");

          if (action === "publish") {
            await env.DB.prepare(
              `
              UPDATE posts
              SET is_published = 1, deleted_at = NULL, updated_at = CURRENT_TIMESTAMP
              WHERE id IN (${placeholders})
              `
            ).bind(...ids).run();

            return json({ ok: true, action, count: ids.length });
          }

          if (action === "unpublish") {
            await env.DB.prepare(
              `
              UPDATE posts
              SET is_published = 0, updated_at = CURRENT_TIMESTAMP
              WHERE id IN (${placeholders})
              AND deleted_at IS NULL
              `
            ).bind(...ids).run();

            return json({ ok: true, action, count: ids.length });
          }

          if (action === "delete") {
            await env.DB.prepare(
              `
              UPDATE posts
              SET is_published = 0, deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
              WHERE id IN (${placeholders})
              AND deleted_at IS NULL
              `
            ).bind(...ids).run();

            return json({ ok: true, action, count: ids.length });
          }

          return json({
            ok: false,
            error: "Invalid bulk action"
          }, 400);
        }

        if (request.method === "POST" && url.pathname === "/admin/posts") {
          const body = await request.json();

          const text = cleanText(body.text);
          const seoTitle = cleanText(body.seo_title);
          const seoDescription = cleanText(body.seo_description);
          const adminNote = cleanText(body.admin_note);
          const media = mediaFromBody(body);

          if (!text) {
            return json({
              ok: false,
              error: "Text is required"
            }, 400);
          }

          const title = makeTitle(text);
          const rawSlug = sanitizeSlug(body.slug || "");
          const slug = rawSlug || makeSlug(title || text);
          const isPublished = body.is_published === false || body.is_published === 0 ? 0 : 1;

          const slugIsUnique = await ensureUniqueSlug(env, slug);

          if (!slugIsUnique) {
            return json({
              ok: false,
              error: "Slug already exists"
            }, 409);
          }

          const result = await env.DB.prepare(
            `
            INSERT INTO posts (
              text,
              slug,
              is_published,
              seo_title,
              seo_description,
              admin_note,
              view_count,
              media_type,
              media_file_id,
              media_unique_id,
              media_mime_type,
              media_file_name,
              media_duration,
              media_width,
              media_height,
              media_size,
              photo_file_id,
              photo_unique_id,
              photo_width,
              photo_height
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            `
          ).bind(
            text,
            slug,
            isPublished,
            seoTitle || null,
            seoDescription || null,
            adminNote || null,
            media.media_type,
            media.media_file_id,
            media.media_unique_id,
            media.media_mime_type,
            media.media_file_name,
            media.media_duration,
            media.media_width,
            media.media_height,
            media.media_size,
            media.photo_file_id,
            media.photo_unique_id,
            media.photo_width,
            media.photo_height
          ).run();
          const mahoonProjectionAdminCreatedId = Number(result.meta?.last_row_id || 0);
          if (mahoonProjectionAdminCreatedId > 0) {
            await mahoonScaleSyncPostTagProjectionV1(
              env,
              mahoonProjectionAdminCreatedId,
              text
            );
          }

          return json({
            ok: true,
            created: true,
            id: result.meta?.last_row_id || null,
            slug
          });
        }

        if (request.method === "POST" && url.pathname.endsWith("/restore") && url.pathname.startsWith("/admin/posts/")) {
          const id = Number(normalizeDigits(url.pathname.replace("/admin/posts/", "").replace("/restore", "")));

          if (!id) {
            return json({
              ok: false,
              error: "Invalid post id"
            }, 400);
          }

          const existing = await env.DB.prepare(
            `
            SELECT id
            FROM posts
            WHERE id = ?
            AND deleted_at IS NOT NULL
            LIMIT 1
            `
          ).bind(id).first();

          if (!existing) {
            return json({
              ok: false,
              error: "Post not found or is not deleted"
            }, 404);
          }

          const result = await env.DB.prepare(
            `
            UPDATE posts
            SET
              is_published = 1,
              deleted_at = NULL,
              updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            AND deleted_at IS NOT NULL
            `
          ).bind(id).run();

          if (!result.meta?.changes || result.meta.changes < 1) {
            return json({
              ok: false,
              error: "Post not found or already restored"
            }, 404);
          }

          const post = await getPostById(env, id);

          return json({
            ok: true,
            restored: true,
            id,
            post: postWithMediaUrl(post, origin)
          });
        }

        if (request.method === "GET" && url.pathname.startsWith("/admin/posts/")) {
          const id = Number(normalizeDigits(url.pathname.replace("/admin/posts/", "")));

          if (!id) {
            return json({
              ok: false,
              error: "Invalid post id"
            }, 400);
          }

          const post = await getPostById(env, id);

          return json({
            ok: true,
            post: postWithMediaUrl(post, origin)
          });
        }

        if (request.method === "PATCH" && url.pathname.startsWith("/admin/posts/")) {
          const id = Number(normalizeDigits(url.pathname.replace("/admin/posts/", "")));

          if (!id) {
            return json({
              ok: false,
              error: "Invalid post id"
            }, 400);
          }

          const existing = await env.DB.prepare(
            `
            SELECT id, slug
            FROM posts
            WHERE id = ?
            AND deleted_at IS NULL
            LIMIT 1
            `
          ).bind(id).first();

          if (!existing) {
            return json({
              ok: false,
              error: "Post not found"
            }, 404);
          }

          const body = await request.json();

          const text = cleanText(body.text);
          const slug = sanitizeSlug(body.slug || existing.slug);
          const seoTitle = cleanText(body.seo_title);
          const seoDescription = cleanText(body.seo_description);
          const adminNote = cleanText(body.admin_note);
          const media = mediaFromBody(body);
          const isPublished = body.is_published === false || body.is_published === 0 ? 0 : 1;

          if (!text) {
            return json({
              ok: false,
              error: "Text is required"
            }, 400);
          }

          if (!slug) {
            return json({
              ok: false,
              error: "Slug is required"
            }, 400);
          }

          const slugIsUnique = await ensureUniqueSlug(env, slug, id);

          if (!slugIsUnique) {
            return json({
              ok: false,
              error: "Slug already exists"
            }, 409);
          }

          await env.DB.prepare(
            `
            UPDATE posts
            SET
              text = ?,
              slug = ?,
              is_published = ?,
              seo_title = ?,
              seo_description = ?,
              admin_note = ?,
              media_type = ?,
              media_file_id = ?,
              media_unique_id = ?,
              media_mime_type = ?,
              media_file_name = ?,
              media_duration = ?,
              media_width = ?,
              media_height = ?,
              media_size = ?,
              photo_file_id = ?,
              photo_unique_id = ?,
              photo_width = ?,
              photo_height = ?,
              updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            `
          ).bind(
            text,
            slug,
            isPublished,
            seoTitle || null,
            seoDescription || null,
            adminNote || null,
            media.media_type,
            media.media_file_id,
            media.media_unique_id,
            media.media_mime_type,
            media.media_file_name,
            media.media_duration,
            media.media_width,
            media.media_height,
            media.media_size,
            media.photo_file_id,
            media.photo_unique_id,
            media.photo_width,
            media.photo_height,
            id
          ).run();
          await mahoonScaleSyncPostTagProjectionV1(env, id, text);

          return json({
            ok: true,
            updated: true,
            id,
            slug
          });
        }

        if (request.method === "DELETE" && url.pathname.startsWith("/admin/posts/")) {
          const id = Number(normalizeDigits(url.pathname.replace("/admin/posts/", "")));

          if (!id) {
            return json({
              ok: false,
              error: "Invalid post id"
            }, 400);
          }

          await env.DB.prepare(
            `
            UPDATE posts
            SET
              is_published = 0,
              deleted_at = CURRENT_TIMESTAMP,
              updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            `
          ).bind(id).run();

          return json({
            ok: true,
            deleted: true,
            id
          });
        }

        return json({
          ok: false,
          error: "Admin endpoint not found"
        }, 404);
      }

      if ((request.method === "GET" || request.method === "HEAD" || request.method === "OPTIONS") && (url.pathname === "/media" || url.pathname.startsWith("/media/"))) {
      // mahoon-force-ios-media-route-v1
      return handleMahooonIosCompatibleMedia(request, env, url);
      // end-mahoon-force-ios-media-route-v1
        const fileId = decodeURIComponent(url.pathname.replace("/media/", ""));

        if (!fileId) {
          return textResponse("File ID is required", 400);
        }

        const telegramFile = await getTelegramFile(fileId, env);

        if (!telegramFile) {
          return textResponse("Media not found", 404);
        }

        return new Response(telegramFile.body, {
          status: 200,
          headers: {
            ...CORS_HEADERS,
            "Content-Type": telegramFile.headers.get("Content-Type") || "application/octet-stream",
            "Cache-Control": "public, max-age=86400"
          }
        });
      }

      if (request.method === "GET" && url.pathname === "/seo/rss-posts") {
        const requestedLimit = Number(normalizeDigits(url.searchParams.get("limit") || "50"));
        const limit = Number.isInteger(requestedLimit) && requestedLimit > 0
          ? Math.min(requestedLimit, 100)
          : 50;

        const { results } = await env.DB.prepare(
          `
          SELECT
            id,
            text,
            slug,
            created_at,
            updated_at,
            media_type,
            media_file_id,
            media_mime_type,
            media_file_name,
            photo_file_id,
            seo_title,
            seo_description
          FROM posts
          WHERE slug IS NOT NULL
          AND slug != ''
          AND deleted_at IS NULL
          AND COALESCE(is_published, 1) = 1
          ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
          LIMIT ?
          `
        ).bind(limit).all();

        return json({
          ok: true,
          posts: (results || []).map(post => rssPostPayload(post, origin)).filter(Boolean)
        });
      }

      if (request.method === "GET" && url.pathname === "/seo/sitemap-posts") {
        const requestedLimit = Number(normalizeDigits(url.searchParams.get("limit") || "1000"));
        const limit = Number.isInteger(requestedLimit) && requestedLimit > 0
          ? Math.min(requestedLimit, 1000)
          : 1000;

        const { results } = await env.DB.prepare(
          `
          SELECT
            id,
            slug,
            created_at,
            updated_at
          FROM posts
          WHERE slug IS NOT NULL
          AND slug != ''
          AND deleted_at IS NULL
          AND COALESCE(is_published, 1) = 1
          ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
          LIMIT ?
          `
        ).bind(limit).all();

        return json({
          ok: true,
          posts: results || []
        });
      }

      if (request.method === "GET" && url.pathname.startsWith("/seo/post/")) {
        const slug = decodeURIComponent(url.pathname.replace("/seo/post/", ""));

        if (!slug) {
          return json({
            ok: false,
            error: "Slug is required"
          }, 400);
        }

        const post = await env.DB.prepare(
          `
          SELECT
            id,
            text,
            slug,
            created_at,
            updated_at,
            media_type,
            media_file_id,
            media_mime_type,
            media_file_name,
            media_width,
            media_height,
            photo_file_id,
            photo_width,
            photo_height,
            seo_title,
            seo_description
          FROM posts
          WHERE slug = ?
          AND slug IS NOT NULL
          AND slug != ''
          AND deleted_at IS NULL
          AND is_published = 1
          LIMIT 1
          `
        ).bind(slug).first();

        if (!post) {
          return json({
            ok: false,
            error: "Post not found"
          }, 404);
        }

        return json({
          ok: true,
          post: seoPostPayload(post, origin)
        });
      }

      if (request.method === "GET" && url.pathname.startsWith("/post/")) {
        const slug = decodeURIComponent(url.pathname.replace("/post/", ""));

        if (!slug) {
          return json({
            ok: false,
            error: "Slug is required"
          }, 400);
        }

        const post = await env.DB.prepare(
          `
          SELECT
            id,
            text,
            slug,
            created_at,
            media_type,
            media_file_id,
            media_unique_id,
            media_mime_type,
            media_file_name,
            media_duration,
            media_width,
            media_height,
            media_size,
            photo_file_id,
            photo_unique_id,
            photo_width,
            photo_height,
            seo_title,
            seo_description,
            COALESCE(view_count, 0) AS view_count,
            last_viewed_at
          FROM posts
          WHERE slug = ?
          AND slug IS NOT NULL
          AND slug != ''
          AND deleted_at IS NULL
          AND COALESCE(is_published, 1) = 1
          LIMIT 1
          `
        ).bind(slug).first();

        if (post) {
          await env.DB.prepare(
            `
            UPDATE posts
            SET
              view_count = COALESCE(view_count, 0) + 1,
              last_viewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            `
          ).bind(post.id).run();

          post.view_count = Number(post.view_count || 0) + 1;
        }

        return json(postWithMediaUrl(post, origin));
      }

      if (request.method === "GET" && url.pathname.startsWith("/id/")) {
        const id = Number(normalizeDigits(url.pathname.replace("/id/", "")));

        if (!id) {
          return json({
            ok: false,
            error: "Invalid post id"
          }, 400);
        }

        const post = await env.DB.prepare(
          `
          SELECT
            id,
            text,
            slug,
            created_at,
            media_type,
            media_file_id,
            media_unique_id,
            media_mime_type,
            media_file_name,
            media_duration,
            media_width,
            media_height,
            media_size,
            photo_file_id,
            photo_unique_id,
            photo_width,
            photo_height,
            seo_title,
            seo_description,
            COALESCE(view_count, 0) AS view_count,
            last_viewed_at
          FROM posts
          WHERE id = ?
          AND deleted_at IS NULL
          AND COALESCE(is_published, 1) = 1
          LIMIT 1
          `
        ).bind(id).first();

        if (post) {
          await env.DB.prepare(
            `
            UPDATE posts
            SET
              view_count = COALESCE(view_count, 0) + 1,
              last_viewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            `
          ).bind(post.id).run();

          post.view_count = Number(post.view_count || 0) + 1;
        }

        return json(postWithMediaUrl(post, origin));
      }

      if (request.method === "GET" && url.pathname === "/") {
        const { results } = await env.DB.prepare(
          `
          SELECT
            id,
            text,
            slug,
            created_at,
            media_type,
            media_file_id,
            media_unique_id,
            media_mime_type,
            media_file_name,
            media_duration,
            media_width,
            media_height,
            media_size,
            photo_file_id,
            photo_unique_id,
            photo_width,
            photo_height,
            seo_title,
            seo_description,
            COALESCE(view_count, 0) AS view_count
          FROM posts
          WHERE slug IS NOT NULL
          AND deleted_at IS NULL
          AND COALESCE(is_published, 1) = 1
          ORDER BY created_at DESC, id DESC
          LIMIT 250
          `
        ).all();

        const publicPosts = (results || [])
          .filter((post) => hasRequiredCategoryHashTag(post.text))
          .slice(0, 100)
          .map(post => postWithMediaUrl(post, origin));

        return json(publicPosts);
      }

      if (request.method === "POST") {
        const update = await request.json();

        const managementResponse = await handleTelegramManagementMessage(update, env);

        if (managementResponse) {
          return managementResponse;
        }

        const telegramPost = extractTelegramPost(update);

        if (!telegramPost) {
          return json({
            ok: true,
            saved: false,
            reason: "No text, caption, command, or media found"
          });
        }

        const title = makeTitle(telegramPost.text);
        const excerpt = makeExcerpt(telegramPost.text);
        const slug = makeSlug(title || telegramPost.text);

        if (telegramPost.is_edited && telegramPost.telegram_message_id) {
          const existing = await env.DB.prepare(
            `
            SELECT id, slug
            FROM posts
            WHERE telegram_message_id = ?
            AND chat_id = ?
            AND deleted_at IS NULL
            LIMIT 1
            `
          ).bind(
            telegramPost.telegram_message_id,
            telegramPost.chat_id
          ).first();

          if (existing) {
            await env.DB.prepare(
              `
              UPDATE posts
              SET
                text = ?,
                media_type = ?,
                media_file_id = ?,
                media_unique_id = ?,
                media_mime_type = ?,
                media_file_name = ?,
                media_duration = ?,
                media_width = ?,
                media_height = ?,
                media_size = ?,
                photo_file_id = ?,
                photo_unique_id = ?,
                photo_width = ?,
                photo_height = ?,
                updated_at = CURRENT_TIMESTAMP
              WHERE id = ?
              `
            ).bind(
              telegramPost.text,
              telegramPost.media_type,
              telegramPost.media_file_id,
              telegramPost.media_unique_id,
              telegramPost.media_mime_type,
              telegramPost.media_file_name,
              telegramPost.media_duration,
              telegramPost.media_width,
              telegramPost.media_height,
              telegramPost.media_size,
              telegramPost.photo_file_id,
              telegramPost.photo_unique_id,
              telegramPost.photo_width,
              telegramPost.photo_height,
              existing.id
            ).run();
            await mahoonScaleSyncPostTagProjectionV1(env, existing.id, telegramPost.text);

            /* mahoon-update-original-telegram-date */
            if (telegramPost.created_at) {
              await env.DB.prepare(
                `
                UPDATE posts
                SET created_at = ?
                WHERE id = ?
                `
              ).bind(telegramPost.created_at, existing.id).run();
            }

            const fresh = await getPostById(env, existing.id);

            await sendSavedPostConfirmation(
              update,
              telegramPost,
              fresh,
              env
            ).catch(() => null);

            return json({
              ok: true,
              saved: true,
              edited: true,
              slug: existing.slug
            });
          }
        }

        const result = await env.DB.prepare(
          `
          INSERT INTO posts (
            text,
            slug,
            telegram_message_id,
            chat_id,
            chat_title,
            media_type,
            media_file_id,
            media_unique_id,
            media_mime_type,
            media_file_name,
            media_duration,
            media_width,
            media_height,
            media_size,
            photo_file_id,
            photo_unique_id,
            photo_width,
            photo_height,
            is_published,
            view_count
          )
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
          `
        ).bind(
          telegramPost.text,
          slug,
          telegramPost.telegram_message_id,
          telegramPost.chat_id,
          telegramPost.chat_title,
          telegramPost.media_type,
          telegramPost.media_file_id,
          telegramPost.media_unique_id,
          telegramPost.media_mime_type,
          telegramPost.media_file_name,
          telegramPost.media_duration,
          telegramPost.media_width,
          telegramPost.media_height,
          telegramPost.media_size,
          telegramPost.photo_file_id,
          telegramPost.photo_unique_id,
          telegramPost.photo_width,
          telegramPost.photo_height
        ).run();
        const mahoonProjectionTelegramCreatedId = Number(result.meta?.last_row_id || 0);
        if (mahoonProjectionTelegramCreatedId > 0) {
          await mahoonScaleSyncPostTagProjectionV1(
            env,
            mahoonProjectionTelegramCreatedId,
            telegramPost.text
          );
        }

        const insertedId = result.meta?.last_row_id || null;

        /* mahoon-insert-original-telegram-date */
        if (insertedId && telegramPost.created_at) {
          await env.DB.prepare(
            `
            UPDATE posts
            SET created_at = ?
            WHERE id = ?
            `
          ).bind(telegramPost.created_at, insertedId).run();
        }
        const savedPost = insertedId ? await getPostById(env, insertedId) : null;

        await sendSavedPostConfirmation(
          update,
          telegramPost,
          savedPost,
          env
        ).catch(() => null);

        return json({
          ok: true,
          saved: true,
          edited: false,
          id: insertedId,
          title,
          excerpt,
          slug,
          media_type: telegramPost.media_type,
          has_media: Boolean(telegramPost.media_file_id)
        });
      }

      return json({
        ok: false,
        error: "Not found"
      }, 404);
    } catch (error) {
      return json({
        ok: false,
        error: error.message || "Unknown error"
      }, 500);
    }
  }
};
