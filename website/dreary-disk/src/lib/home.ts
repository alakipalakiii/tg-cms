export type HomePost = {
  id?: number | string;
  telegram_message_id?: number | string;
  text?: string | null;
  caption?: string | null;
  slug?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  date?: string | null;
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

export type HomeCategory = {
  title: string;
  tags: string[];
};

export type HomeStats = {
  visible_posts?: number;
  active_categories?: number;
  latest_id?: number;
  text_posts?: number;
  category_map?: Record<string, number>;
};

export type HomeCategoryResult = {
  category: HomeCategory;
  posts: HomePost[];
  total: number;
  ok: boolean;
};

export type HomeSnapshot = {
  ok: boolean;
  status: number;
  posts: HomePost[];
  stats: HomeStats | null;
  categories: HomeCategoryResult[];
  error: string;
};

export type HomeAdConfig = {
  rightEnabled?: unknown;
  rightTitle?: string;
  rightText?: string;
  rightUrl?: string;
  rightButton?: string;
  rightPosition?: string;
  rightImage?: string;
  leftEnabled?: unknown;
  leftTitle?: string;
  leftText?: string;
  leftUrl?: string;
  leftButton?: string;
  leftPosition?: string;
  leftImage?: string;
};

export type HomeAdRenderResult = {
  html: string;
  count: number;
};

type NormalizedHomePost = HomePost & {
  id: number | string;
  text: string;
  slug: string | number;
  created_at: string;
  media_type: string;
  photo_file_id: string;
  media_file_id: string;
  seo_title: string;
  seo_description: string;
};

type HomeAd = {
  key: string;
  enabled: boolean;
  title: string;
  text: string;
  url: string;
  button: string;
  position: string;
  image: string;
};

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

function escapeRegex(value: unknown): string {
  return String(value || "")
    .replace(/[.*+?^$()|[\]\\]/g, "\\$&")
    .replace(/[{}]/g, "\\$&");
}

function toPersianNumber(value: unknown): string {
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

function normalizeTag(tag: unknown): string {
  return String(tag || "")
    .replace(/^#/, "")
    .replace(/[يى]/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/\u200c/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function getTags(text: unknown): string[] {
  return Array.from(new Set(
    Array.from(String(text || "").matchAll(/(^|\s)#([^\s#]+)/gu))
      .map((match) => match[2])
      .filter(Boolean)
  ));
}

function stripMovieCreditLines(value: unknown): string {
  return String(value || "")
    .split(/\r?\n/)
    .filter((line) => {
      const trimmed = line.trim();
      if (!trimmed) return true;
      return !/^(?:🎥|🎬|فیلم\s*:?)\s*#?\s*.+$/iu.test(trimmed);
    })
    .join("\n");
}

function extractMovieTitle(value: unknown): string {
  const lines = String(value || "").split(/\r?\n/);

  for (const line of lines) {
    const match = line.trim().match(/^(?:🎥|🎬|فیلم\s*:?)\s*#?\s*(.+)$/iu);
    if (match?.[1]) return match[1].replace(/^#/, "").trim();
  }

  return "";
}

function removeMovieNames(value: unknown, post: HomePost): string {
  let text = String(value || "");
  const movieTitle = extractMovieTitle(post?.text || "");

  const names = [
    movieTitle,
    "The Walking Dead",
    "House M.D",
    "House MD",
    "Indecent Proposal",
    "Funny Face"
  ].filter(Boolean);

  for (const name of names) {
    text = text.replace(new RegExp(escapeRegex(name), "giu"), " ");
  }

  return text
    .replace(/🎥|🎬/g, " ")
    .replace(/\s+([،؛,.!])/g, "$1")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function cleanPublicText(value: unknown): string {
  return String(stripMovieCreditLines(value) || "")
    .replace(/\u{1F539}?\s*@mahoonartmagazine/giu, "")
    .replace(/https?:\/\/[^\s]+/giu, "")
    .replace(/@[a-zA-Z0-9_]+/g, "")
    .replace(/(^|\s)#([^\n#]+)/gu, " ")
    .replace(/[🎥🎬]/gu, "")
    .replace(/[؟?]/g, "")
    .replace(/[•●▪▫◦]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function cleanPostText(post: HomePost, value: unknown): string {
  return cleanPublicText(removeMovieNames(value, post));
}

function truncateText(value: unknown, maximum: number): string {
  const source = String(value || "").replace(/\s+/g, " ").trim();
  if (!source) return "";
  return source.length <= maximum
    ? source
    : source.slice(0, maximum).trim() + "…";
}

function firstWords(value: unknown, maximum: number): string {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .filter(Boolean)
    .slice(0, maximum)
    .join(" ");
}

function isDialoguePost(post: HomePost): boolean {
  return /#(?:دیالوگ|دیالوگ‌ها|دیالوگ_ها)/u.test(String(post.text || ""));
}

function makeTitle(post: HomePost): string {
  const seoTitle = cleanPostText(post, post.seo_title);
  if (seoTitle && seoTitle.length <= 70) return truncateText(seoTitle, 70);

  const source = cleanPostText(post, post.text);
  const title = truncateText(firstWords(source, 8), 64);

  if (title) return title;
  if (isDialoguePost(post)) return "دیالوگی از فیلم";
  return "مطلبی از ماهون";
}

function makeExcerpt(post: HomePost, maximum = 72): string {
  const source = cleanPostText(post, post.seo_description) || cleanPostText(post, post.text);
  return truncateText(source || "روایتی تازه از مجله هنری ماهون", maximum);
}

function formatDate(value: unknown): string {
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

function postHref(post: HomePost): string {
  const slug = String(post.slug || post.id || "").trim();
  return "/post/" + encodeURIComponent(slug);
}

function isAudioPost(post: HomePost): boolean {
  return ["audio", "voice", "music"].includes(String(post.media_type || "").toLowerCase());
}

function isVideoPost(post: HomePost): boolean {
  return ["video", "animation"].includes(String(post.media_type || "").toLowerCase());
}

function mediaSrc(post: HomePost, apiBase: string, forceTextOnly = false): string {
  if (forceTextOnly) return "";

  const type = String(post.media_type || "").toLowerCase();
  const direct = post.photo_url || post.image_url || post.thumbnail_url;

  if (direct) return String(direct);
  if (post.photo_file_id) return `${apiBase}/media/${encodeURIComponent(String(post.photo_file_id))}`;

  if ((type === "photo" || type === "image") && post.media_file_id) {
    return `${apiBase}/media/${encodeURIComponent(String(post.media_file_id))}`;
  }

  return "";
}

function pencilIcon(): string {
  return '<svg viewBox="0 0 64 64" aria-hidden="true"><path d="M43.6 8.8a6.5 6.5 0 0 1 9.2 9.2L25.1 45.7l-12.3 3.5 3.5-12.3L43.6 8.8Z"></path><path d="M38.8 13.6 48 22.8"></path><path d="M12 55h40"></path></svg>';
}

function audioIcon(): string {
  return '<svg viewBox="0 0 64 64" aria-hidden="true"><path d="M22 44H12a4 4 0 0 1-4-4V24a4 4 0 0 1 4-4h10l18-12v48L22 44Z"></path><path d="M47 23a12 12 0 0 1 0 18"></path><path d="M52 16a22 22 0 0 1 0 32"></path></svg>';
}

function videoIcon(): string {
  return '<svg viewBox="0 0 64 64" aria-hidden="true"><rect x="8" y="14" width="36" height="36" rx="7"></rect><path d="M44 27l12-8v26l-12-8V27Z"></path></svg>';
}

function normalizePost(raw: HomePost): NormalizedHomePost | null {
  const id = raw?.id ?? raw?.telegram_message_id ?? "";
  if (!id) return null;

  return {
    ...raw,
    id,
    text: String(raw?.text || raw?.caption || ""),
    slug: String(raw?.slug || id),
    created_at: String(raw?.created_at || raw?.date || raw?.updated_at || ""),
    media_type: String(raw?.media_type || ""),
    photo_file_id: String(raw?.photo_file_id || ""),
    media_file_id: String(raw?.media_file_id || ""),
    seo_title: String(raw?.seo_title || ""),
    seo_description: String(raw?.seo_description || "")
  };
}

function extractPosts(payload: any): HomePost[] {
  const source = Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.posts)
      ? payload.posts
      : Array.isArray(payload?.data)
        ? payload.data
        : [];

  return source
    .map((post: HomePost) => normalizePost(post))
    .filter(Boolean) as HomePost[];
}

function publicTags(post: HomePost, categories: HomeCategory[]): string[] {
  const categoryTags = new Set(
    categories.flatMap((category) => category.tags.map(normalizeTag))
  );
  const movieTitle = normalizeTag(extractMovieTitle(post.text));

  return getTags(post.text)
    .filter((tag) => !categoryTags.has(normalizeTag(tag)))
    .filter((tag) => normalizeTag(tag) !== movieTitle)
    .filter((tag) => !/^the\s+walking\s+dead$/i.test(String(tag).trim()))
    .filter((tag) => !/^house\s*m\.?d$/i.test(String(tag).trim()))
    .filter((tag) => !/^indecent\s+proposal$/i.test(String(tag).trim()))
    .filter((tag) => !/^funny\s+face$/i.test(String(tag).trim()))
    .slice(0, 3);
}

function renderTags(post: HomePost, categories: HomeCategory[]): string {
  const tags = publicTags(post, categories);
  if (!tags.length) return "";

  return '<div class="m-tags">' + tags.map((tag) =>
    '<a href="/tag/' + encodeURIComponent(tag) + '">#' + escapeHtml(tag) + '</a>'
  ).join("") + '</div>';
}

async function fetchJson(url: string, timeoutMs: number): Promise<{
  ok: boolean;
  status: number;
  payload: any;
  error: string;
}> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: controller.signal
    });

    const payload = await response.json().catch(() => null);

    return {
      ok: response.ok && payload?.ok !== false,
      status: response.status,
      payload,
      error: response.ok ? String(payload?.error || "") : `HTTP ${response.status}`
    };
  } catch (error) {
    return {
      ok: false,
      status: 503,
      payload: null,
      error: error instanceof Error ? error.message : String(error)
    };
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchHomeSnapshot(options: {
  apiBase: string;
  categories: HomeCategory[];
  timeoutMs?: number;
}): Promise<HomeSnapshot> {
  const apiBase = String(options.apiBase || "").replace(/\/+$/, "");
  const timeoutMs = Math.max(1500, Number(options.timeoutMs || 6000));
  const categories = Array.isArray(options.categories) ? options.categories : [];

  const homeUrl = new URL(`${apiBase}/public/home-v1`);
  homeUrl.searchParams.set("limit", "20");

  const homePromise = fetchJson(homeUrl.toString(), timeoutMs);
  const categoryPromises = categories.map(async (category) => {
    const url = new URL(`${apiBase}/public/posts-v1`);
    url.searchParams.set("category", category.title);
    url.searchParams.set("limit", "10");
    url.searchParams.set("offset", "0");

    const result = await fetchJson(url.toString(), timeoutMs);

    return {
      category,
      posts: extractPosts(result.payload),
      total: Math.max(0, Number(result.payload?.total || 0)),
      ok: result.ok,
      error: result.error
    };
  });
  const [homeResult, categoryResults] = await Promise.all([
    homePromise,
    Promise.all(categoryPromises)
  ]);

  const posts = extractPosts(homeResult.payload);
  const stats = homeResult.payload?.stats || null;
  const categoriesPayload = categoryResults.map((result) => ({
    category: result.category,
    posts: result.posts,
    total: result.total,
    ok: result.ok
  }));
  const categoryFailure = categoryResults.find((result) => !result.ok);
  const ok = homeResult.ok && posts.length > 0 && !categoryFailure;

  return {
    ok,
    status: ok ? 200 : 503,
    posts,
    stats,
    categories: categoriesPayload,
    error: homeResult.error || categoryFailure?.error || (!posts.length ? "No public posts" : "")
  };
}

export function renderHomeFeaturedHtml(options: {
  post?: HomePost | null;
  apiBase: string;
  categories: HomeCategory[];
}): string {
  const post = options.post;
  if (!post) return "";

  const apiBase = options.apiBase.replace(/\/+$/, "");
  const title = makeTitle(post);
  const image = mediaSrc(post, apiBase);
  const href = postHref(post);
  let media = "";

  if (image) {
    media = '<a class="m-featured__media" href="' + escapeAttr(href) + '"><img src="' + escapeAttr(image) + '" alt="' + escapeAttr(title) + '" loading="lazy" decoding="async"></a>';
  } else if (isAudioPost(post)) {
    media = '<a class="m-featured__media m-featured__media--icon" href="' + escapeAttr(href) + '">' + audioIcon() + '</a>';
  } else if (isVideoPost(post)) {
    media = '<a class="m-featured__media m-featured__media--icon" href="' + escapeAttr(href) + '">' + videoIcon() + '</a>';
  }

  return '<article class="m-featured ' + (!media ? "m-featured--text" : "") + '">' +
    media +
    '<div class="m-featured__body">' +
      '<div class="m-meta"><span>' + escapeHtml(formatDate(post.created_at)) + '</span></div>' +
      '<h2>' + escapeHtml(title) + '</h2>' +
      '<p>' + escapeHtml(makeExcerpt(post, 86)) + '</p>' +
      renderTags(post, options.categories) +
      '<a class="m-btn" href="' + escapeAttr(href) + '">ادامه مطلب</a>' +
    '</div>' +
  '</article>';
}

export function renderHomeStatsHtml(stats: HomeStats | null, latestPosts: HomePost[]): string {
  const visible = Number(stats?.visible_posts || latestPosts.length || 0);
  const active = Number(stats?.active_categories || 0);
  const latestId = Number(stats?.latest_id || latestPosts[0]?.id || 0);
  const textPosts = Number(stats?.text_posts || 0);

  return '<article><strong>' + toPersianNumber(visible) + '</strong><span>مطالب منتشرشده</span></article>' +
    '<article><strong>' + toPersianNumber(active) + '</strong><span>دسته‌بندی فعال</span></article>' +
    '<article><strong>' + toPersianNumber(latestId) + '</strong><span>آخرین کد مطلب</span></article>' +
    '<article><strong>' + toPersianNumber(textPosts) + '</strong><span>مطالب متنی</span></article>';
}

export function renderHomeListHtml(posts: HomePost[], apiBase: string): string {
  const normalizedApiBase = apiBase.replace(/\/+$/, "");

  return posts.slice(0, 20).map((post) => {
    const title = makeTitle(post);
    const image = mediaSrc(post, normalizedApiBase);
    const href = postHref(post);
    let thumb = "";
    let thumbClass = "";

    if (image) {
      thumb = '<img src="' + escapeAttr(image) + '" alt="' + escapeAttr(title) + '" loading="lazy" decoding="async">';
    } else if (isAudioPost(post)) {
      thumb = audioIcon();
      thumbClass = "m-list-row__thumb--icon";
    } else if (isVideoPost(post)) {
      thumb = videoIcon();
      thumbClass = "m-list-row__thumb--icon";
    } else {
      thumb = pencilIcon();
      thumbClass = "m-list-row__thumb--icon";
    }

    return '<a class="m-list-row" href="' + escapeAttr(href) + '">' +
      '<span class="m-list-row__thumb ' + thumbClass + '">' + thumb + '</span>' +
      '<span class="m-list-row__copy">' +
        '<strong>' + escapeHtml(title) + '</strong>' +
        '<small>' + escapeHtml(formatDate(post.created_at)) + '</small>' +
      '</span>' +
    '</a>';
  }).join("");
}

function renderHomeCardHtml(post: HomePost, apiBase: string, forceTextOnly = false): string {
  const title = makeTitle(post);
  const image = mediaSrc(post, apiBase, forceTextOnly);
  const href = postHref(post);
  let media = "";

  if (image) {
    media = '<a class="m-card__media" href="' + escapeAttr(href) + '"><img src="' + escapeAttr(image) + '" alt="' + escapeAttr(title) + '" loading="lazy" decoding="async"></a>';
  } else if (!forceTextOnly && isAudioPost(post)) {
    media = '<a class="m-card__media m-card__media--icon" href="' + escapeAttr(href) + '">' + audioIcon() + '</a>';
  } else if (!forceTextOnly && isVideoPost(post)) {
    media = '<a class="m-card__media m-card__media--icon" href="' + escapeAttr(href) + '">' + videoIcon() + '</a>';
  }

  return '<article class="m-card ' + (!media ? "m-card--no-media" : "") + '" data-post-href="' + escapeAttr(href) + '">' +
    media +
    '<div class="m-card__body">' +
      '<span class="m-card__date">' + escapeHtml(formatDate(post.created_at)) + '</span>' +
      '<h3>' + escapeHtml(title) + '</h3>' +
      '<p>' + escapeHtml(makeExcerpt(post, 68)) + '</p>' +
      '<a class="m-card__cta" href="' + escapeAttr(href) + '">ادامه مطلب</a>' +
    '</div>' +
  '</article>';
}

function normalizeAdPosition(value: unknown): string {
  const allowed = new Set([
    "after_latest",
    "after_all_posts",
    "before_categories",
    "after_category_1",
    "after_category_2",
    "after_category_3",
    "after_category_4",
    "after_category_5",
    "after_categories"
  ]);
  const position = String(value || "").trim();
  return allowed.has(position) ? position : "before_categories";
}

function isAdEnabled(value: unknown): boolean {
  const text = String(value ?? "").trim().toLowerCase();
  if (!text) return false;
  return !["0", "false", "off", "no", "خاموش", "غیرفعال"].includes(text);
}

function homeAds(config: HomeAdConfig): HomeAd[] {
  return [
    {
      key: "right",
      enabled: isAdEnabled(config.rightEnabled ?? "1"),
      title: config.rightTitle || "",
      text: config.rightText || "",
      url: config.rightUrl || "",
      button: config.rightButton || "مشاهده",
      position: normalizeAdPosition(config.rightPosition),
      image: config.rightImage || ""
    },
    {
      key: "left",
      enabled: isAdEnabled(config.leftEnabled ?? "1"),
      title: config.leftTitle || "",
      text: config.leftText || "",
      url: config.leftUrl || "",
      button: config.leftButton || "مشاهده",
      position: normalizeAdPosition(config.leftPosition),
      image: config.leftImage || ""
    }
  ].filter((ad) => ad.enabled && Boolean(ad.title || ad.text || ad.image));
}

function renderAdCard(ad: HomeAd): string {
  const title = ad.title || "جایگاه تبلیغات";
  const text = ad.text || "";
  const button = ad.button || "مشاهده";
  const image = ad.image || "";
  const imageHtml = image
    ? '<div class="m-ad-card__image"><img src="' + escapeAttr(image) + '" alt="' + escapeAttr(title) + '" loading="lazy" decoding="async"></div>'
    : "";
  const actionHtml = ad.url
    ? '<a href="' + escapeAttr(ad.url) + '" target="_blank" rel="noopener">' + escapeHtml(button) + '</a>'
    : '<span>' + escapeHtml(button) + '</span>';

  return '<article class="m-ad-card ' + (image ? "m-ad-card--with-image" : "") + '">' +
    imageHtml +
    '<strong>' + escapeHtml(title) + '</strong>' +
    (text ? '<p>' + escapeHtml(text) + '</p>' : "") +
    actionHtml +
  '</article>';
}

export function renderHomeAdsHtml(config: HomeAdConfig, position: string): HomeAdRenderResult {
  const items = homeAds(config).filter((ad) => ad.position === position);

  return {
    html: items.map(renderAdCard).join(""),
    count: items.length
  };
}

function renderDynamicAdsSection(config: HomeAdConfig, position: string): string {
  const result = renderHomeAdsHtml(config, position);
  if (!result.count) return "";

  return '<section class="m-ads m-ads--dynamic ' + (result.count === 1 ? "m-ads--single" : "") + '" aria-label="تبلیغات">' +
    result.html +
  '</section>';
}

export function renderHomeCategoriesHtml(options: {
  categories: HomeCategoryResult[];
  stats: HomeStats | null;
  apiBase: string;
  ads: HomeAdConfig;
}): string {
  const categoryMap = options.stats?.category_map || {};
  const apiBase = options.apiBase.replace(/\/+$/, "");

  return options.categories.map((item, index) => {
    const category = item.category;
    const posts = item.posts || [];
    const total = Number(item.total ?? categoryMap[category.title] ?? posts.length);

    if (!posts.length && !total) return "";

    const tone = index % 2 === 0 ? "m-rail--light" : "m-rail--dark";
    const forceTextOnly = category.title === "شعر و متن";
    const allHref = "/category/" + encodeURIComponent(category.title);

    return '<section class="m-rail ' + tone + '">' +
      '<header class="m-rail__head">' +
        '<div><span>دسته‌بندی ماهون</span><h2>' + escapeHtml(category.title) + '</h2></div>' +
        '<div class="m-rail__actions">' +
          '<a href="' + escapeAttr(allHref) + '">مشاهده همه ' + toPersianNumber(total) + ' مطلب</a>' +
          '<button type="button" data-rail-btn data-dir="-1" aria-label="قبلی">‹</button>' +
          '<button type="button" data-rail-btn data-dir="1" aria-label="بعدی">›</button>' +
        '</div>' +
      '</header>' +
      '<div class="m-card-strip">' +
        posts.slice(0, 10).map((post) => renderHomeCardHtml(post, apiBase, forceTextOnly)).join("") +
      '</div>' +
    '</section>' +
    renderDynamicAdsSection(options.ads, "after_category_" + (index + 1));
  }).join("");
}
