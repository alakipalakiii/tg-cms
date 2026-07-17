export type TagPost = {
  id?: number | string;
  text?: string | null;
  slug?: string | null;
  created_at?: string | null;
  media_type?: string | null;
  media_url?: string | null;
  photo_url?: string | null;
  photo_file_id?: string | null;
  media_file_id?: string | null;
  file_id?: string | null;
  telegram_file_id?: string | null;
  image_url?: string | null;
  thumbnail_url?: string | null;
  file_url?: string | null;
  seo_title?: string | null;
  seo_description?: string | null;
};

export type TagPageResult = {
  ok: boolean;
  status: number;
  posts: TagPost[];
  total: number;
  limit: number;
  offset: number;
  nextOffset: number;
  hasMore: boolean;
  error: string;
};

type CardKind =
  | "book"
  | "dialogue"
  | "audio"
  | "art"
  | "text"
  | "video"
  | "photo";

export function safeDecodeTagValue(value: string | null | undefined): string {
  try {
    return decodeURIComponent(String(value || ""));
  } catch {
    return String(value || "");
  }
}

export function normalizeTagValue(tag: string | null | undefined): string {
  return String(tag || "")
    .replace(/^#/, "")
    .replace(/[يى]/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/[\u200c\u200f]/g, "")
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

export function toPersianTagNumber(value: unknown): string {
  return new Intl.NumberFormat("fa-IR").format(Number(value || 0));
}

function escapeHtml(value: unknown): string {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(value: unknown): string {
  return escapeHtml(value).replace(/'/g, "&#039;");
}

function removeEmoji(value: string | null | undefined): string {
  return String(value || "")
    .replace(/[\p{Extended_Pictographic}\uFE0F]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function extractMovieTitle(value: string | null | undefined): string {
  const lines = String(value || "").split(/\r?\n/);

  for (const rawLine of lines) {
    const line = rawLine.trim();
    const match = line.match(/^(?:🎥|🎬|فیلم\s*:?)\s*#?\s*(.+)$/iu);

    if (!match) continue;

    const title = match[1]
      .replace(/[🔹•●▪▫◦]+/gu, "")
      .replace(/@mahoonartmagazine/giu, "")
      .replace(/^#/, "")
      .replace(/_/g, " ")
      .replace(/\s+/g, " ")
      .trim();

    if (title) return title;
  }

  return "";
}

function getRawHashTags(text: string | null | undefined): string[] {
  return Array.from(String(text || "").matchAll(/(^|\s)#([^\s#]+)/gu))
    .map((match) => match[2])
    .filter(Boolean);
}

function hasExactTag(text: string | null | undefined, variants: string[]): boolean {
  const expected = new Set(variants.map(normalizeTagValue));
  return getRawHashTags(text).some((tag) => expected.has(normalizeTagValue(tag)));
}

function hasDialogueTag(text: string | null | undefined): boolean {
  return hasExactTag(text, [
    "دیالوگ",
    "دیالوگ‌ها",
    "دیالوگ_ها",
    "دیالوگ ها",
    "دیالوگها"
  ]);
}

function cleanPublicText(value: string | null | undefined): string {
  return removeEmoji(
    String(value || "")
      .replace(/\u{1F539}?\s*@mahoonartmagazine/giu, "")
      .replace(/\u{1F539}/gu, "")
      .replace(/(^|\n)\s*(?:🎥|🎬|فیلم\s*:?)\s*#?\s*[^\n]+/giu, "\n")
      .replace(/https?:\/\/(?:t\.me|telegram\.me|telegram\.dog)\/[^\s]+/giu, "")
      .replace(/https?:\/\/[^\s]+/giu, "")
      .replace(/@[a-zA-Z0-9_]+/g, "")
      .replace(/(^|\s)#([^\s#]+)/gu, " ")
      .replace(/[•●▪▫◦]/g, "")
      .replace(/_/g, " ")
      .replace(/\n{3,}/g, "\n\n")
      .replace(/[ \t]{2,}/g, " ")
      .trim()
  );
}

function limitWords(value: string | null | undefined, maximum: number): string {
  const words = String(value || "")
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .filter(Boolean);

  if (!words.length) return "";
  if (words.length <= maximum) return words.join(" ");
  return words.slice(0, maximum).join(" ") + "…";
}

function makeDisplayTitle(post: TagPost): string {
  const movieTitle = extractMovieTitle(post.text);

  if (movieTitle && hasDialogueTag(post.text)) {
    return "دیالوگی از فیلم " + limitWords(movieTitle, 6);
  }

  const seoTitle = cleanPublicText(post.seo_title);
  if (seoTitle) return limitWords(seoTitle, 5);

  return limitWords(cleanPublicText(post.text), 5) || "مطلبی از ماهون";
}

function removeInsensitiveTagText(source: unknown, token: unknown): string {
  let result = String(source || "");
  const target = String(token || "");
  if (!target) return result;

  let lowerResult = result.toLowerCase();
  const lowerTarget = target.toLowerCase();
  let index = lowerResult.indexOf(lowerTarget);

  while (index >= 0) {
    result = result.slice(0, index) + " " + result.slice(index + target.length);
    lowerResult = result.toLowerCase();
    index = lowerResult.indexOf(lowerTarget);
  }

  return result;
}

function cleanTagExcerpt(value: unknown, movieTitle: string): string {
  return removeInsensitiveTagText(value, movieTitle)
    .replace(/[\p{Extended_Pictographic}\uFE0F]/gu, " ")
    .replace(/#\S+/gu, " ")
    .replace(/@mahoonartmagazine/giu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function makeExcerpt(post: TagPost): string {
  const movieTitle = extractMovieTitle(post.text);
  const raw = post.seo_description || post.text || "";
  const source = cleanTagExcerpt(cleanPublicText(raw), movieTitle);
  return limitWords(source, 14) || "روایتی تازه از مجله هنری ماهون";
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "";

  try {
    return new Intl.DateTimeFormat("fa-IR", {
      year: "numeric",
      month: "long",
      day: "numeric"
    }).format(new Date(String(value).replace(" ", "T")));
  } catch {
    return String(value || "");
  }
}

function validMediaValue(value: string | null | undefined): string | null {
  const source = String(value || "").trim();

  if (!source || /^(null|undefined)$/i.test(source)) return null;
  return source;
}

function mediaUrlFromId(apiBase: string, value: string | null | undefined): string | null {
  const source = validMediaValue(value);
  if (!source) return null;
  return apiBase.replace(/\/+$/, "") + "/media/" + encodeURIComponent(source);
}

function getMediaSrc(post: TagPost, apiBase: string): string | null {
  const direct = [
    post.media_url,
    post.photo_url,
    post.image_url,
    post.thumbnail_url,
    post.file_url
  ].map(validMediaValue).find(Boolean);

  if (direct) return direct;

  return mediaUrlFromId(
    apiBase,
    post.photo_file_id ||
      post.media_file_id ||
      post.file_id ||
      post.telegram_file_id
  );
}

function getPostHref(post: TagPost): string {
  const slug = String(post.slug || "").trim();
  return "/post/" + encodeURIComponent(slug || String(post.id || ""));
}

function primaryKind(post: TagPost): CardKind {
  if (hasExactTag(post.text, ["کتاب", "کتاب گویا", "کتاب_گویا", "کتابگویا"])) return "book";
  if (hasDialogueTag(post.text)) return "dialogue";
  if (hasExactTag(post.text, ["صوتی", "صدا", "موسیقی"])) return "audio";
  if (hasExactTag(post.text, ["نقاشی"])) return "art";

  if (hasExactTag(post.text, [
    "شعر و متن",
    "شعر_و_متن",
    "شعر",
    "اشعار",
    "شعرها",
    "شعر ها",
    "شعر_ها",
    "متن",
    "متن‌ها",
    "متن ها",
    "متن_ها"
  ])) return "text";

  const mediaType = String(post.media_type || "").toLowerCase();
  if (mediaType === "audio" || mediaType === "voice") return "audio";
  if (mediaType === "video" || mediaType === "animation") return "video";
  if (mediaType === "photo" || mediaType === "image") return "photo";
  return "text";
}

function kindLabel(kind: CardKind): string {
  if (kind === "book") return "کتاب";
  if (kind === "dialogue") return "دیالوگ";
  if (kind === "audio") return "صوتی";
  if (kind === "art") return "نقاشی";
  if (kind === "video") return "ویدیو";
  if (kind === "photo") return "تصویری";
  return "متن";
}

function kindIcon(kind: CardKind): string {
  if (kind === "book") return "▤";
  if (kind === "dialogue") return "❞";
  if (kind === "audio") return "♪";
  if (kind === "art") return "◐";
  if (kind === "video") return "▶";
  if (kind === "photo") return "◇";
  return "✎";
}

function searchText(post: TagPost): string {
  return normalizeTagValue([
    post.text,
    post.seo_title,
    post.seo_description,
    post.slug,
    makeDisplayTitle(post),
    makeExcerpt(post)
  ].join(" "));
}

export function renderTagCardHtml(post: TagPost, apiBase: string): string {
  const kind = primaryKind(post);
  const label = kindLabel(kind);
  const title = makeDisplayTitle(post);
  const excerpt = makeExcerpt(post);
  const image = getMediaSrc(post, apiBase);
  const href = getPostHref(post);

  const media = image
    ? `<img src="${escapeAttr(image)}" alt="${escapeAttr(title)}" width="720" height="430" loading="lazy" decoding="async" />`
    : `<span class="mahoon-tag-card__icon" aria-hidden="true">${escapeHtml(kindIcon(kind))}</span>`;

  return `<article class="mahoon-tag-card mahoon-tag-card--${escapeAttr(kind)}" data-tag-card data-search="${escapeAttr(searchText(post))}">` +
    `<a class="mahoon-tag-card__media ${image ? "" : "mahoon-tag-card__media--placeholder"}" href="${escapeAttr(href)}">` +
      media +
      `<span class="mahoon-tag-card__badge">${escapeHtml(label)}</span>` +
    `</a>` +
    `<div class="mahoon-tag-card__body">` +
      `<div class="mahoon-tag-card__meta"><span>${escapeHtml(formatDate(post.created_at))}</span><span>${escapeHtml(label)}</span></div>` +
      `<h2><a href="${escapeAttr(href)}">${escapeHtml(title)}</a></h2>` +
      `<p>${escapeHtml(excerpt)}</p>` +
      `<a class="mahoon-tag-card__cta" href="${escapeAttr(href)}">ادامه مطلب</a>` +
    `</div>` +
  `</article>`;
}

export function renderTagCardsHtml(posts: TagPost[], apiBase: string): string {
  return posts.map((post) => renderTagCardHtml(post, apiBase)).join("");
}

export async function fetchPublicTagPage(options: {
  apiBase: string;
  tag: string;
  query?: string;
  limit?: number;
  offset?: number;
  timeoutMs?: number;
}): Promise<TagPageResult> {
  const apiBase = String(options.apiBase || "").replace(/\/+$/, "");
  const limit = Math.max(1, Math.min(Number(options.limit || 20), 120));
  const offset = Math.max(0, Number(options.offset || 0));
  const url = new URL(`${apiBase}/public/tag-posts-v1`);

  url.searchParams.set("tag", options.tag);
  url.searchParams.set("limit", String(limit));
  url.searchParams.set("offset", String(offset));
  if (options.query) url.searchParams.set("q", options.query);

  const controller = new AbortController();
  const timer = setTimeout(
    () => controller.abort(),
    Math.max(1000, Number(options.timeoutMs || 6000))
  );

  try {
    const response = await fetch(url.toString(), {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: controller.signal
    });
    const payload = await response.json().catch(() => null);

    if (!response.ok || payload?.ok === false) {
      return {
        ok: false,
        status: response.status || 503,
        posts: [],
        total: 0,
        limit,
        offset,
        nextOffset: offset,
        hasMore: false,
        error: String(payload?.error || `HTTP ${response.status}`)
      };
    }

    const posts = Array.isArray(payload?.posts) ? payload.posts as TagPost[] : [];
    const total = Math.max(0, Number(payload?.total || 0));
    const nextOffset = Math.max(offset, Number(payload?.next_offset ?? offset + posts.length));

    return {
      ok: true,
      status: 200,
      posts,
      total,
      limit,
      offset,
      nextOffset,
      hasMore: Boolean(payload?.has_more),
      error: ""
    };
  } catch (error) {
    return {
      ok: false,
      status: 503,
      posts: [],
      total: 0,
      limit,
      offset,
      nextOffset: offset,
      hasMore: false,
      error: error instanceof Error ? error.message : String(error)
    };
  } finally {
    clearTimeout(timer);
  }
}
