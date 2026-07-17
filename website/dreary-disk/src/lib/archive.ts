export type ArchivePost = {
  id?: number | string;
  text?: string | null;
  slug?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  media_type?: string | null;
  media_url?: string | null;
  photo_url?: string | null;
  photo_file_id?: string | null;
  media_file_id?: string | null;
  image_url?: string | null;
  thumbnail_url?: string | null;
  seo_title?: string | null;
  seo_description?: string | null;
};

export type ArchiveCategory = {
  title: string;
  tags: string[];
};

export type ArchivePageResult = {
  ok: boolean;
  status: number;
  posts: ArchivePost[];
  total: number;
  limit: number;
  offset: number;
  nextOffset: number;
  hasMore: boolean;
  error: string;
};

export const ARCHIVE_CATEGORIES: ArchiveCategory[] = [
  { title: "کتاب", tags: ["کتاب"] },
  { title: "دیالوگ ها", tags: ["دیالوگ", "دیالوگ‌ها", "دیالوگ_ها"] },
  { title: "صوتی", tags: ["صوتی", "صدا", "موسیقی"] },
  { title: "شعر و متن", tags: ["متن", "متن‌ها", "متن_ها", "شعر", "اشعار", "شعرها", "شعر_ها"] },
  { title: "نقاشی", tags: ["نقاشی"] }
];

export function safeDecodeArchiveValue(value: string | null | undefined): string {
  try {
    return decodeURIComponent(String(value || ""));
  } catch {
    return String(value || "");
  }
}

export function normalizeArchiveToken(value: string | null | undefined): string {
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

export function findArchiveCategory(value: string | null | undefined): ArchiveCategory | null {
  const normalized = normalizeArchiveToken(value);

  return ARCHIVE_CATEGORIES.find((category) => {
    if (normalizeArchiveToken(category.title) === normalized) return true;
    return category.tags.some((tag) => normalizeArchiveToken(tag) === normalized);
  }) || null;
}

export function toPersianNumber(value: unknown): string {
  return String(value ?? "")
    .replace(/0/g, "۰")
    .replace(/1/g, "۱")
    .replace(/2/g, "۲")
    .replace(/3/g, "۳")
    .replace(/4/g, "۴")
    .replace(/5/g, "۵")
    .replace(/6/g, "۶")
    .replace(/7/g, "۷")
    .replace(/8/g, "۸")
    .replace(/9/g, "۹");
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

function formatDate(value: string | null | undefined): string {
  if (!value) return "";

  try {
    return new Intl.DateTimeFormat("fa-IR", {
      year: "numeric",
      month: "long",
      day: "numeric"
    }).format(new Date(String(value).replace(" ", "T")));
  } catch {
    return "";
  }
}

function stripMovieCreditLines(value: unknown): string {
  return String(value || "")
    .split(/\r?\n/)
    .filter((line) => {
      const trimmed = line.trim();
      if (!trimmed) return true;

      if (/^(?:\u{1F3A5}|\u{1F3AC}|فیلم\s*:?)\s*#?\s*.+$/iu.test(trimmed)) return false;
      if (/^(?:Queen to Play|Dogville|The Walking Dead|House\s*M\.?D\.?|The Tourist|Indecent Proposal|Funny Face)$/iu.test(trimmed)) return false;

      return true;
    })
    .join("\n");
}

function removeKnownMovieNames(value: unknown): string {
  return String(value || "")
    .replace(/[\u{1F3A5}\u{1F3AC}]/gu, " ")
    .replace(/دیالوگی?\s+از\s+فیلم\s+[^،؛.!؟\n]+/giu, " ")
    .replace(/فیلم\s*:?[\s‌]+[^،؛.!؟\n]+/giu, " ")
    .replace(/Queen to Play/gi, " ")
    .replace(/Dogville/gi, " ")
    .replace(/The Walking Dead/gi, " ")
    .replace(/House\s*M\.?D\.?/gi, " ")
    .replace(/The Tourist/gi, " ")
    .replace(/Indecent Proposal/gi, " ")
    .replace(/Funny Face/gi, " ")
    .replace(/#\S+/gu, " ")
    .replace(/@mahoonartmagazine/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function cleanPublicText(value: unknown): string {
  return removeKnownMovieNames(stripMovieCreditLines(value))
    .replace(/#\S+/gu, " ")
    .replace(/[\u{1F3A5}\u{1F3AC}]/gu, " ")
    .replace(/@mahoonartmagazine/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function limitWords(value: unknown, maxWords: number): string {
  const words = String(value || "")
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .filter(Boolean);

  if (!words.length) return "";
  if (words.length <= maxWords) return words.join(" ");
  return words.slice(0, maxWords).join(" ") + "…";
}

function postTags(post: ArchivePost): string[] {
  const matches = String(post.text || "").matchAll(/(^|\s)#([^\s#@]+)/gu);
  return Array.from(matches).map((match) => normalizeArchiveToken(match[2]));
}

function hasExactArchiveTag(post: ArchivePost, names: string[]): boolean {
  const tags = postTags(post);
  return names.some((name) => tags.includes(normalizeArchiveToken(name)));
}

function primaryKindFromTags(post: ArchivePost): string {
  if (hasExactArchiveTag(post, ["کتاب", "کتاب گویا", "کتاب_گویا", "کتابگویا"])) return "book";

  if (hasExactArchiveTag(post, [
    "دیالوگ",
    "دیالوگ ها",
    "دیالوگ_ها",
    "دیالوگ‌ها",
    "دیالوگها"
  ])) return "dialogue";

  if (hasExactArchiveTag(post, ["صوتی", "صدا", "موسیقی"])) return "audio";
  if (hasExactArchiveTag(post, ["نقاشی"])) return "art";

  if (hasExactArchiveTag(post, [
    "شعر و متن",
    "شعر_و_متن",
    "شعر",
    "اشعار",
    "شعرها",
    "شعر ها",
    "شعر_ها",
    "متن",
    "متن ها",
    "متن_ها",
    "متن‌ها"
  ])) return "text";

  return "";
}

function normalizeMovieTitleCandidate(value: unknown): string {
  return String(value || "")
    .replace(/[\u{1F3A5}\u{1F3AC}]/gu, " ")
    .replace(/^\s*دیالوگی?\s+از\s+فیلم\s*/iu, " ")
    .replace(/^\s*فیلم\s*[:：-]?\s*/iu, " ")
    .replace(/^\s*#/, "")
    .replace(/#\S+/gu, " ")
    .replace(/@mahoonartmagazine/gi, " ")
    .replace(/[،؛.!؟]+$/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function isValidMovieTitleCandidate(value: unknown): boolean {
  const clean = String(value || "").trim();

  if (!clean || clean.length < 2 || clean.length > 48) return false;
  if (/^(دیالوگ|دیالوگی|فیلم|متن|کتاب|صوتی)$/iu.test(clean)) return false;

  return true;
}

function extractMovieTitle(post: ArchivePost): string {
  const raw = String(post.text || "");
  const lines = raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  for (const line of lines) {
    if (/[\u{1F3A5}\u{1F3AC}]/u.test(line) || /فیلم\s*[:：-]?/iu.test(line) || /دیالوگی?\s+از\s+فیلم/iu.test(line)) {
      const candidate = normalizeMovieTitleCandidate(line);

      if (isValidMovieTitleCandidate(candidate)) {
        return candidate;
      }
    }
  }

  const knownMovies = [
    "Queen to Play",
    "Dogville",
    "The Walking Dead",
    "House M.D",
    "The Tourist",
    "Indecent Proposal",
    "Funny Face"
  ];

  const lower = raw.toLowerCase();

  for (const movie of knownMovies) {
    if (lower.includes(movie.toLowerCase())) return movie;
  }

  return "";
}

function makeTitle(post: ArchivePost, category: string): string {
  const source = cleanPublicText(post.text);
  const seo = cleanPublicText(post.seo_title);
  const isDialogue = category === "دیالوگ ها" || primaryKindFromTags(post) === "dialogue";

  if (isDialogue) {
    const movieTitle = extractMovieTitle(post);
    if (movieTitle) return "دیالوگی از فیلم " + limitWords(movieTitle, 6);
    return "دیالوگی از ماهون";
  }

  if (seo) return limitWords(seo, 5);
  return limitWords(source, 5) || "مطلبی از ماهون";
}

function excerptMovieTitle(post: ArchivePost): string {
  const raw = String(post.text || "");
  const lines = raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  for (const line of lines) {
    const match = line.match(/^(?:🎥|🎬|فیلم\s*:?)\s*#?\s*(.+)$/iu);

    if (match?.[1]) {
      return String(match[1])
        .replace(/[🔹•●▪▫◦]+/gu, " ")
        .replace(/@mahoonartmagazine/giu, " ")
        .replace(/^#/, "")
        .replace(/_/g, " ")
        .replace(/\s+/g, " ")
        .trim();
    }
  }

  const known = [
    "Queen to Play",
    "Dogville",
    "The Walking Dead",
    "House M.D",
    "The Tourist",
    "Indecent Proposal",
    "Funny Face",
    "Westworld"
  ];

  const lower = raw.toLowerCase();
  return known.find((title) => lower.includes(title.toLowerCase())) || "";
}

function removeInsensitiveText(source: unknown, token: unknown): string {
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

function cleanExcerptText(value: unknown, movieTitle: string): string {
  let source = String(value || "");
  source = removeInsensitiveText(source, movieTitle);

  return source
    .replace(/[\p{Extended_Pictographic}\uFE0F]/gu, " ")
    .replace(/#\S+/gu, " ")
    .replace(/@mahoonartmagazine/giu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function makeExcerpt(post: ArchivePost): string {
  const movieTitle = excerptMovieTitle(post);
  const raw = post.seo_description || post.text || "";
  const source = cleanExcerptText(cleanPublicText(raw), movieTitle);
  return limitWords(source, 14);
}

function postHref(post: ArchivePost): string {
  const slug = String(post.slug || post.id || "").trim();
  return "/post/" + encodeURIComponent(slug);
}

function mediaKind(post: ArchivePost, category: string): string {
  const type = String(post.media_type || "").toLowerCase();

  if (category === "کتاب") return "book";
  if (category === "دیالوگ ها") return "dialogue";
  if (category === "صوتی") return "audio";
  if (category === "شعر و متن") return "text";
  if (category === "نقاشی") return "art";

  const tagKind = primaryKindFromTags(post);
  if (tagKind) return tagKind;

  if (type === "audio" || type === "voice") return "audio";
  if (type === "video" || type === "animation") return "video";
  if (type === "photo" || type === "image") return "photo";

  return "text";
}

function mediaLabel(kind: string): string {
  if (kind === "audio") return "صوتی";
  if (kind === "video") return "ویدیو";
  if (kind === "book") return "کتاب";
  if (kind === "dialogue") return "دیالوگ";
  if (kind === "art") return "نقاشی";
  if (kind === "photo") return "تصویری";
  return "متن";
}

function mediaIcon(kind: string): string {
  if (kind === "audio") return "♪";
  if (kind === "video") return "▶";
  if (kind === "book") return "▤";
  if (kind === "dialogue") return "❞";
  if (kind === "art") return "◐";
  if (kind === "photo") return "◇";
  return "✎";
}

function mediaSrc(post: ArchivePost, apiBase: string): string {
  const type = String(post.media_type || "").toLowerCase();
  const direct = post.photo_url || post.image_url || post.thumbnail_url || "";

  if (direct) return String(direct);

  const photoId = post.photo_file_id;
  if (photoId) return `${apiBase}/media/${encodeURIComponent(String(photoId))}`;

  if ((type === "photo" || type === "image") && post.media_file_id) {
    return `${apiBase}/media/${encodeURIComponent(String(post.media_file_id))}`;
  }

  return "";
}

export function renderArchiveCardHtml(
  post: ArchivePost,
  options: { apiBase: string; category?: string }
): string {
  const category = String(options.category || "");
  const title = makeTitle(post, category);
  const excerpt = makeExcerpt(post);
  const kind = mediaKind(post, category);
  const label = mediaLabel(kind);
  const image = mediaSrc(post, options.apiBase.replace(/\/+$/, ""));
  const href = postHref(post);

  const mediaInner = image
    ? `<img src="${escapeAttr(image)}" alt="${escapeAttr(title)}" loading="lazy" decoding="async" />`
    : `<span class="mahoon-archive-card__icon" aria-hidden="true">${escapeHtml(mediaIcon(kind))}</span>`;

  return `<article class="mahoon-archive-card mahoon-archive-card--${escapeAttr(kind)}">` +
    `<a class="mahoon-archive-card__media ${image ? "" : "mahoon-archive-card__media--placeholder"}" data-kind="${escapeAttr(kind)}" href="${escapeAttr(href)}">` +
      mediaInner +
      `<span class="mahoon-archive-card__badge">${escapeHtml(label)}</span>` +
    `</a>` +
    `<div class="mahoon-archive-card__body">` +
      `<div class="mahoon-archive-card__meta">` +
        `<span class="mahoon-archive-date">${escapeHtml(formatDate(post.created_at))}</span>` +
        `<span class="mahoon-archive-kind">${escapeHtml(label)}</span>` +
      `</div>` +
      `<h2><a href="${escapeAttr(href)}">${escapeHtml(title)}</a></h2>` +
      `<p>${escapeHtml(excerpt)}</p>` +
      `<a class="mahoon-archive-cta" href="${escapeAttr(href)}">ادامه مطلب</a>` +
    `</div>` +
  `</article>`;
}

export function renderArchiveCardsHtml(
  posts: ArchivePost[],
  options: { apiBase: string; category?: string }
): string {
  return posts.map((post) => renderArchiveCardHtml(post, options)).join("");
}

export async function fetchPublicArchivePage(options: {
  apiBase: string;
  category?: string;
  query?: string;
  limit?: number;
  offset?: number;
  timeoutMs?: number;
}): Promise<ArchivePageResult> {
  const apiBase = String(options.apiBase || "").replace(/\/+$/, "");
  const limit = Math.max(1, Math.min(Number(options.limit || 20), 120));
  const offset = Math.max(0, Number(options.offset || 0));
  const url = new URL(`${apiBase}/public/posts-v1`);

  url.searchParams.set("limit", String(limit));
  url.searchParams.set("offset", String(offset));

  if (options.category) url.searchParams.set("category", options.category);
  if (options.query) url.searchParams.set("q", options.query);

  const controller = new AbortController();
  const timer = setTimeout(
    () => controller.abort(),
    Math.max(1000, Number(options.timeoutMs || 5000))
  );

  try {
    const response = await fetch(url.toString(), {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: controller.signal
    });

    if (!response.ok) {
      return {
        ok: false,
        status: response.status,
        posts: [],
        total: 0,
        limit,
        offset,
        nextOffset: offset,
        hasMore: false,
        error: `HTTP ${response.status}`
      };
    }

    const payload = await response.json() as Record<string, unknown>;
    const posts = Array.isArray(payload.posts) ? payload.posts as ArchivePost[] : [];
    const total = Math.max(0, Number(payload.total || 0));
    const nextOffset = Math.max(
      offset,
      Number(payload.next_offset ?? offset + posts.length)
    );

    return {
      ok: payload.ok !== false,
      status: 200,
      posts,
      total,
      limit,
      offset,
      nextOffset,
      hasMore: Boolean(payload.has_more),
      error: payload.ok === false ? String(payload.error || "API response was not successful") : ""
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
