import { SEO_CACHE_CONTROL, buildRobots } from '../utils/seoDocuments';

export default defineEventHandler((event) => {
  const config = useRuntimeConfig(event);
  setResponseHeaders(event, { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': SEO_CACHE_CONTROL });
  return buildRobots(config.public.siteUrl);
});
