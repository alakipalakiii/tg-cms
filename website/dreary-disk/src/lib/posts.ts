import { SITE } from "../config";

export type Post = {
  id: number;
  text: string;
  slug: string;
  created_at: string;

  media_type?: string | null;
  media_file_id?: string | null;
  media_unique_id?: string | null;
  media_mime_type?: string | null;
  media_file_name?: string | null;
  media_duration?: number | null;
  media_width?: number | null;
  media_height?: number | null;
  media_size?: number | null;
  media_url?: string | null;

  photo_file_id?: string | null;
  photo_unique_id?: string | null;
  photo_width?: number | null;
  photo_height?: number | null;
  photo_url?: string | null;

  seo_title?: string | null;
  seo_description?: string | null;
  view_count?: number | null;
  last_viewed_at?: string | null;
};

export type ParsedPostContent = {
  title: string;
  content: string;
  excerpt: string;
  hashtags: string[];
  mentions: string[];
  urls: string[];
  searchText: string;
};

const HASHTAG_REGEX = /#[\p{L}\p{N}_]+/gu;
const MENTION_REGEX = /@[\w.]+/g;
const URL_REGEX = /(https?:\/\/[^\s]+)/g;

function unique(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)));
}

function normalizeText(text?: string) {
  return (text || "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .trim();
}

export function parsePostContent(text?: string): ParsedPostContent {
  const original = normalizeText(text);

  if (!original) {
    return {
      title: "پست بدون عنوان",
      content: "",
      excerpt: "",
      hashtags: [],
      mentions: [],
      urls: [],
      searchText: ""
    };
  }

  const hashtags = unique(
    (original.match(HASHTAG_REGEX) || []).map(tag =>
      tag.replace("#", "").trim()
    )
  );

  const urls = unique(original.match(URL_REGEX) || []);

  const lines = original.split("\n");
  const cleanLines: string[] = [];

  for (const rawLine of lines) {
    const line = rawLine.trim();

    if (!line) {
      if (cleanLines.length > 0 && cleanLines[cleanLines.length - 1] !== "") {
        cleanLines.push("");
      }
      continue;
    }

    const cleanedLine = line
      .replace(URL_REGEX, "")
      .replace(HASHTAG_REGEX, "")
      .replace(MENTION_REGEX, "")
      .replace(/[◆◇🔹🔸▪️•]+/g, "")
      .replace(/\s+/g, " ")
      .trim();

    if (!cleanedLine) continue;

    cleanLines.push(cleanedLine);
  }

  while (cleanLines[cleanLines.length - 1] === "") {
    cleanLines.pop();
  }

  const content = cleanLines.join("\n").trim();

  const firstLine =
    cleanLines.find(line => line.trim()) ||
    original
      .replace(MENTION_REGEX, "")
      .replace(HASHTAG_REGEX, "")
      .replace(URL_REGEX, "")
      .split("\n")[0] ||
    "پست بدون عنوان";

  const title =
    firstLine
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 90) || "پست بدون عنوان";

  const excerptSource = content
    .replace(/\n/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  const excerpt =
    excerptSource.length > 180
      ? excerptSource.slice(0, 180) + "..."
      : excerptSource;

  return {
    title,
    content: content || original.replace(MENTION_REGEX, "").trim(),
    excerpt,
    hashtags,
    mentions: [],
    urls,
    searchText: `${title} ${excerpt} ${hashtags.join(" ")} ${urls.join(" ")}`
  };
}

export function makeTitle(text?: string) {
  return parsePostContent(text).title;
}

export function makeExcerpt(text?: string, length = 180) {
  const parsed = parsePostContent(text);
  const clean = parsed.content.replace(/\n/g, " ").replace(/\s+/g, " ").trim();
  return clean.length > length ? clean.slice(0, length) + "..." : clean;
}

export function formatDate(value?: string) {
  if (!value) return "";

  try {
    const date = new Date(value.replace(" ", "T") + "Z");

    return new Intl.DateTimeFormat("fa-IR", {
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    }).format(date);
  } catch {
    return value;
  }
}

function normalizePost(post: any): Post | null {
  if (!post) return null;
  if (!post.id || !post.text || !post.slug) return null;

  return {
    id: Number(post.id),
    text: String(post.text),
    slug: String(post.slug),
    created_at: post.created_at ? String(post.created_at) : "",

    media_type: post.media_type ? String(post.media_type) : null,
    media_file_id: post.media_file_id ? String(post.media_file_id) : null,
    media_unique_id: post.media_unique_id ? String(post.media_unique_id) : null,
    media_mime_type: post.media_mime_type ? String(post.media_mime_type) : null,
    media_file_name: post.media_file_name ? String(post.media_file_name) : null,
    media_duration: post.media_duration ? Number(post.media_duration) : null,
    media_width: post.media_width ? Number(post.media_width) : null,
    media_height: post.media_height ? Number(post.media_height) : null,
    media_size: post.media_size ? Number(post.media_size) : null,
    media_url: post.media_url ? String(post.media_url) : null,

    photo_file_id: post.photo_file_id ? String(post.photo_file_id) : null,
    photo_unique_id: post.photo_unique_id ? String(post.photo_unique_id) : null,
    photo_width: post.photo_width ? Number(post.photo_width) : null,
    photo_height: post.photo_height ? Number(post.photo_height) : null,
    photo_url: post.photo_url ? String(post.photo_url) : null,

    seo_title: post.seo_title ? String(post.seo_title) : null,
    seo_description: post.seo_description ? String(post.seo_description) : null,
    view_count: post.view_count ? Number(post.view_count) : 0,
    last_viewed_at: post.last_viewed_at ? String(post.last_viewed_at) : null
  };
}

export async function getPosts(): Promise<Post[]> {
  try {
    const res = await fetch(SITE.workerUrl, {
      headers: {
        Accept: "application/json"
      }
    });

    if (!res.ok) return [];

    const data = await res.json();

    if (!Array.isArray(data)) return [];

    return data
      .map(normalizePost)
      .filter(Boolean)
      .sort((a, b) => b!.id - a!.id) as Post[];
  } catch {
    return [];
  }
}

export async function getPostBySlug(slug: string): Promise<Post | null> {
  try {
    const res = await fetch(`${SITE.workerUrl}/post/${slug}`, {
      headers: {
        Accept: "application/json"
      }
    });

    if (!res.ok) return null;

    const data = await res.json();

    return normalizePost(data);
  } catch {
    return null;
  }
}

export function escapeXml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}