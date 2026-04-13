"""
Brave Search API Client for Storewright
Real-time web search with freshness filters for product research.
"""

import os
import httpx
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

BRAVE_API_BASE = "https://api.search.brave.com/res/v1"
BRAVE_DEFAULT_TIMEOUT = 30

@dataclass
class BraveSearchResult:
    title: str
    url: str
    description: str
    page_fetched: Optional[str] = None
    type: str = "search"

@dataclass 
class BraveSearchResponse:
    query: str
    results: List[BraveSearchResult]
    total_results: int

class BraveSearchClient:
    """
    Brave Search API client for real-time web search.
    Docs: https://api-dashboard.search.brave.com/app/documentation
    """
    
    def __init__(self, api_key: str, timeout: int = BRAVE_DEFAULT_TIMEOUT):
        self.api_key = api_key
        self.timeout = timeout
    
    def _headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key,
        }
    
    def search(
        self,
        query: str,
        country: Optional[str] = None,
        search_lang: Optional[str] = None,
        freshness: Optional[str] = None,
        extra_snippets: bool = True,
        count: int = 20,
        offset: int = 0,
    ) -> BraveSearchResponse:
        """
        Perform a web search.
        
        Args:
            query: Search query
            country: 2-letter country code (e.g., "US", "GB", "NG")
            search_lang: Content language filter (e.g., "en")
            freshness: Date filter - "pd" (24h), "pw" (7d), "pm" (31d), "py" (year)
            extra_snippets: Get up to 5 additional excerpts per result
            count: Number of results (max 20)
            offset: Pagination offset
        
        Returns:
            BraveSearchResponse with results
        """
        params = {
            "q": query,
            "count": min(count, 20),
            "offset": offset,
        }
        
        if country:
            params["country"] = country
        if search_lang:
            params["search_lang"] = search_lang
        if freshness:
            params["freshness"] = freshness
        if extra_snippets:
            params["extra_snippets"] = "true"
        
        url = f"{BRAVE_API_BASE}/web/search"
        
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(
                url,
                headers=self._headers(),
                params=params,
            )
            response.raise_for_status()
            data = response.json()
        
        # Parse results
        results = []
        web_results = data.get("web", {}).get("results", [])
        
        for item in web_results:
            result = BraveSearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                description=item.get("description", ""),
                page_fetched=item.get("page_fetched"),
                type=item.get("type", "search"),
            )
            results.append(result)
        
        return BraveSearchResponse(
            query=query,
            results=results,
            total_results=len(results),
        )
    
    def search_trending_products(
        self,
        niche: str = "",
        country: str = "US",
        days: int = 7,
    ) -> List[Dict[str, Any]]:
        """
        Search for trending dropshipping products.
        
        Args:
            niche: Product niche (e.g., "fitness", "home decor")
            country: Target market country
            days: How recent (7 for past week, 30 for month)
        
        Returns:
            List of product opportunities with sources
        """
        freshness = "pw" if days <= 7 else "pm" if days <= 31 else "py"
        
        queries = [
            f"{niche} trending dropshipping products 2026" if niche else "trending dropshipping products April 2026",
            f"viral TikTok products {niche} 2026",
            f"best selling Amazon products {niche} April 2026",
            f"{niche} product trends 2026",
        ]
        
        all_results = []
        seen_urls = set()
        
        for query in queries:
            try:
                response = self.search(
                    query=query,
                    country=country,
                    freshness=freshness,
                    extra_snippets=True,
                )
                
                for result in response.results:
                    if result.url not in seen_urls:
                        all_results.append({
                            "title": result.title,
                            "url": result.url,
                            "description": result.description,
                            "source": "brave_search",
                            "query": query,
                        })
                        seen_urls.add(result.url)
            except Exception as e:
                print(f"[Brave Search] Query failed: {query} - {e}")
                continue
        
        return all_results


def get_brave_client() -> BraveSearchClient:
    """Get Brave Search client from environment."""
    api_key = os.environ.get("BRAVE_API_KEY", "")
    if not api_key:
        raise ValueError("BRAVE_API_KEY environment variable not set")
    return BraveSearchClient(api_key)
