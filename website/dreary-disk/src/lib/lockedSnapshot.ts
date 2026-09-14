import snapshot from "../generated/locked-published-content.json";
import {
  dedupePublicListingPosts,
  sortPublicListingPosts,
  type PublicListingPost
} from "./publicListingDedupe";

export type LockedSnapshotPost = PublicListingPost & {
  slug: string;
  updated_at?: string | null;
  media_type?: string | null;
  media_mime_type?: string | null;
  media_file_name?: string | null;
  media_duration?: number | null;
  media_width?: number | null;
  media_height?: number | null;
  media_size?: number | null;
  seo_title?: string | null;
  seo_description?: string | null;
  canonical_category?: string | null;
};

export function sortLockedSnapshotPosts(posts: LockedSnapshotPost[]): LockedSnapshotPost[] {
  return sortPublicListingPosts(posts);
}

const sourcePosts = Array.isArray((snapshot as { posts?: unknown }).posts)
  ? (snapshot as { posts: LockedSnapshotPost[] }).posts
  : [];

export const LOCKED_SNAPSHOT_POSTS = sortLockedSnapshotPosts(sourcePosts);
export const LOCKED_PUBLIC_LISTING_POSTS = dedupePublicListingPosts(LOCKED_SNAPSHOT_POSTS);

export function lockedSnapshotPosts(category?: string): LockedSnapshotPost[] {
  return category
    ? LOCKED_PUBLIC_LISTING_POSTS.filter((post) => post.canonical_category === category)
    : LOCKED_PUBLIC_LISTING_POSTS;
}
