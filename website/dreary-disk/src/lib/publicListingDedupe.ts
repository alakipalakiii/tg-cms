export type PublicListingPost = {
  id: number;
  slug?: string | null;
  text?: string | null;
  created_at?: string | null;
  media_unique_id?: string | null;
  photo_unique_id?: string | null;
  media_file_id?: string | null;
  photo_file_id?: string | null;
};

const PUBLIC_LISTING_DUPLICATE_WINDOW_MS = 10 * 60 * 1000;

function timestamp(value: unknown): number {
  const parsed = Date.parse(String(value || "").replace(" ", "T"));
  return Number.isFinite(parsed) ? parsed : 0;
}

function normalizedListingText(value: unknown): string {
  return String(value || "")
    .normalize("NFKC")
    .replace(/[\u200B-\u200F\u202A-\u202E\u2060\uFEFF]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function publicListingKey(post: PublicListingPost): string {
  const mediaIdentity = String(
    post.media_unique_id || post.photo_unique_id || post.media_file_id || post.photo_file_id || ""
  ).trim();
  return normalizedListingText(post.text) + "\u0000" + mediaIdentity;
}

export function sortPublicListingPosts<T extends PublicListingPost>(posts: T[]): T[] {
  return [...posts].sort((left, right) =>
    timestamp(right.created_at) - timestamp(left.created_at) || right.id - left.id
  );
}

export function dedupePublicListingPosts<T extends PublicListingPost>(posts: T[]): T[] {
  const sorted = sortPublicListingPosts(posts);
  const lastSeen = new Map<string, number>();
  const result: T[] = [];

  for (const post of sorted) {
    const key = publicListingKey(post);
    const current = timestamp(post.created_at);
    const previous = lastSeen.get(key) || 0;
    const isAdjacentSourceDuplicate =
      current > 0 && previous > 0 && Math.abs(previous - current) <= PUBLIC_LISTING_DUPLICATE_WINDOW_MS;

    if (!isAdjacentSourceDuplicate) result.push(post);
    if (current > 0) lastSeen.set(key, current);
  }

  return result;
}
