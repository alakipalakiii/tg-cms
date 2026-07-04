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
      photo_file_id: null,
      photo_unique_id: null,
      photo_width: null,
      photo_height: null
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
    is_edited: Boolean(update.edited_channel_post || update.edited_message),
    ...media
  };
}

function postWithMediaUrl(post, origin) {
  if (!post) return null;

  const fallbackFileId = post.media_file_id || post.photo_file_id || null;
  const resolvedMediaType = post.media_type || (post.photo_file_id ? "photo" : null);
  const mediaUrl = fallbackFileId
    ? `${origin}/media/${encodeURIComponent(fallbackFileId)}`
    : null;

  return {
    ...post,
    media_type: resolvedMediaType,
    media_file_id: fallbackFileId,
    media_url: mediaUrl,
    photo_url: resolvedMediaType === "photo" && mediaUrl ? mediaUrl : null
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
    ORDER BY id DESC
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
      SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
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

        if (request.method === "GET" && url.pathname === "/admin/posts/deleted") {
          const requestedLimit = Number(normalizeDigits(url.searchParams.get("limit") || "100"));
          const limit = Number.isInteger(requestedLimit) && requestedLimit > 0
            ? Math.min(requestedLimit, 200)
            : 100;

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
            ORDER BY deleted_at DESC, id DESC
            LIMIT ?
            `
          ).bind(limit).all();

          return json({
            ok: true,
            posts: (results || []).map(post => postWithMediaUrl(post, origin))
          });
        }

        if (request.method === "GET" && url.pathname === "/admin/posts") {
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
            WHERE deleted_at IS NULL
            ORDER BY id DESC
            LIMIT 500
            `
          ).all();

          return json({
            ok: true,
            posts: (results || []).map(post => postWithMediaUrl(post, origin))
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
              SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
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

      if (request.method === "GET" && url.pathname.startsWith("/media/")) {
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
          ORDER BY id DESC
          LIMIT 100
          `
        ).all();

        return json((results || []).map(post => postWithMediaUrl(post, origin)));
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

        const insertedId = result.meta?.last_row_id || null;
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
