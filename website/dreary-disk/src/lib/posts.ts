import { SITE } from "../config";

export type Post = {
  id: number;
  text: string;
  slug: string;
  created_at: string;
  updated_at?: string | null;

  telegram_message_id?: number | null;
  chat_id?: string | null;
  chat_title?: string | null;

  media_type?: string | null;
  media_file_id?: string | null;
  media_unique_id?: string | null;
  media_mime_type?: string | null;
  media_file_name?: string | null;
  media_duration?: number | null;
  media_width?: number | null;
  media_height?: number | null;
  media_size?: number | null;

  photo_file_id?: string | null;
  photo_unique_id?: string | null;
  photo_width?: number | null;
  photo_height?: number | null;

  media_url?: string | null;
  photo_url?: string | null;

  is_published?: number | boolean | null;
  deleted_at?: string | null;

  seo_title?: string | null;
  seo_description?: string | null;
  admin_note?: string | null;
  view_count?: number | null;
  last_viewed_at?: string | null;
};

export type ParsedPostContent = {
  cleanText: string;
  hashtags: string[];
  urls: string[];
  mentions: string[];
};

const API_BASE = SITE.workerUrl.replace(/\/+$/, "");

function asText(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

function asNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function normalizePost(raw: any): Post {
  const mediaFileId = raw?.media_file_id || raw?.photo_file_id || null;
  const mediaType = raw?.media_type || (raw?.photo_file_id ? "photo" : null);

  const generatedMediaUrl =
    mediaFileId ? `${API_BASE}/media/${encodeURIComponent(mediaFileId)}` : null;

  const mediaUrl = raw?.media_url || generatedMediaUrl;
  const photoUrl =
    raw?.photo_url ||
    (mediaType === "photo" ? mediaUrl : null) ||
    (raw?.photo_file_id
      ? `${API_BASE}/media/${encodeURIComponent(raw.photo_file_id)}`
      : null);

  return {
    id: Number(raw?.id || 0),
    text: asText(raw?.text),
    slug: asText(raw?.slug || `post-${raw?.id || Date.now()}`),
    created_at: asText(raw?.created_at || new Date().toISOString()),
    updated_at: raw?.updated_at || null,

    telegram_message_id: asNumber(raw?.telegram_message_id),
    chat_id: raw?.chat_id || null,
    chat_title: raw?.chat_title || null,

    media_type: mediaType,
    media_file_id: mediaFileId,
    media_unique_id: raw?.media_unique_id || raw?.photo_unique_id || null,
    media_mime_type: raw?.media_mime_type || null,
    media_file_name: raw?.media_file_name || null,
    media_duration: asNumber(raw?.media_duration),
    media_width: asNumber(raw?.media_width || raw?.photo_width),
    media_height: asNumber(raw?.media_height || raw?.photo_height),
    media_size: asNumber(raw?.media_size),

    photo_file_id: raw?.photo_file_id || null,
    photo_unique_id: raw?.photo_unique_id || null,
    photo_width: asNumber(raw?.photo_width),
    photo_height: asNumber(raw?.photo_height),

    media_url: mediaUrl,
    photo_url: photoUrl,

    is_published: raw?.is_published ?? 1,
    deleted_at: raw?.deleted_at || null,

    seo_title: raw?.seo_title || null,
    seo_description: raw?.seo_description || null,
    admin_note: raw?.admin_note || null,
    view_count: asNumber(raw?.view_count) || 0,
    last_viewed_at: raw?.last_viewed_at || null
  };
}

function extractPosts(payload: any): Post[] {
  if (Array.isArray(payload)) {
    return payload.map(normalizePost).filter((post) => post.id);
  }

  if (Array.isArray(payload?.posts)) {
    return payload.posts.map(normalizePost).filter((post) => post.id);
  }

  if (Array.isArray(payload?.data)) {
    return payload.data.map(normalizePost).filter((post) => post.id);
  }

  if (payload?.id) {
    return [normalizePost(payload)];
  }

  return [];
}

async function fetchJson(url: string): Promise<any> {
  const response = await fetch(url, {
    method: "GET",
    headers: {
      Accept: "application/json"
    },
    cache: "no-store"
  });

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

export async function getPosts(limit?: number): Promise<Post[]> {
  try {
    const payload = await fetchJson(`${API_BASE}/`);
    const posts = extractPosts(payload)
      .filter((post) => !post.deleted_at)
      .sort((a, b) => {
        const dateA = new Date(a.created_at).getTime();
        const dateB = new Date(b.created_at).getTime();
        return dateB - dateA;
      });

    if (typeof limit === "number" && limit > 0) {
      return posts.slice(0, limit);
    }

    return posts;
  } catch (error) {
    console.error("Mahoon getPosts error:", error);
    return [];
  }
}

export async function getPostBySlug(slug: string): Promise<Post | null> {
  try {
    const payload = await fetchJson(`${API_BASE}/post/${encodeURIComponent(slug)}`);
    const posts = extractPosts(payload);

    if (posts.length > 0) {
      return posts[0];
    }

    return null;
  } catch (error) {
    console.error("Mahoon getPostBySlug direct error:", error);

    const posts = await getPosts();
    return posts.find((post) => post.slug === slug) || null;
  }
}

export function parsePostContent(text: string | null | undefined): ParsedPostContent {
  const originalText = asText(text);

  const urls = Array.from(
    new Set(originalText.match(/https?:\/\/[^\s]+/giu) || [])
  );

  const hashtags = Array.from(
    new Set(
      Array.from(originalText.matchAll(/(^|\s)#([^\s#]+)/gu))
        .map((match) => match[2])
        .filter(Boolean)
    )
  );

  const mentions = Array.from(
    new Set(originalText.match(/@[a-zA-Z0-9_]+/g) || [])
  ).filter((mention) => mention.toLowerCase() !== "@mahoonartmagazine");

  let cleanText = originalText
    .replace(/https?:\/\/[^\s]+/giu, "")
    .replace(/@[a-zA-Z0-9_]+/g, "")
    .replace(/(^|\s)#([^\s#]+)/gu, " ")
    .replace(/[•●▪▫◦]/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]{2,}/g, " ")
    .trim();

  return {
    cleanText,
    hashtags,
    urls,
    mentions: []
  };
}

export function makeTitle(text: string | null | undefined): string {
  const parsed = parsePostContent(text);
  const source = parsed.cleanText || "روایت ماهون";

  const firstLine =
    source
      .split("\n")
      .map((line) => line.trim())
      .find(Boolean) || "روایت ماهون";

  if (firstLine.length <= 62) return firstLine;

  return `${firstLine.slice(0, 62).trim()}...`;
}

export function makeExcerpt(text: string | null | undefined, maxLength = 150): string {
  const parsed = parsePostContent(text);
  const source = parsed.cleanText.replace(/\s+/g, " ").trim();

  if (!source) return "روایتی تازه از مجله هنری ماهون";
  if (source.length <= maxLength) return source;

  return `${source.slice(0, maxLength).trim()}...`;
}

export function formatDate(dateString: string | null | undefined): string {
  if (!dateString) return "";

  try {
    const date = new Date(dateString.replace(" ", "T"));

    return new Intl.DateTimeFormat("fa-IR", {
      year: "numeric",
      month: "long",
      day: "numeric"
    }).format(date);
  } catch {
    return String(dateString);
  }
}

export function escapeXml(value: string | null | undefined): string {
  return asText(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

export function getPostTags(post: Post): string[] {
  return parsePostContent(post.text).hashtags;
}

export function getAllTags(posts: Post[]): string[] {
  return Array.from(
    new Set(posts.flatMap((post) => getPostTags(post)))
  ).sort((a, b) => a.localeCompare(b, "fa"));
}

export function getPostsByTag(posts: Post[], tag: string): Post[] {
  const normalizedTag = tag.replace(/^#/, "").trim();

  return posts.filter((post) =>
    getPostTags(post).some((item) => item === normalizedTag)
  );
}