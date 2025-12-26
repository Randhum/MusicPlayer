"""Automatic metadata fetching from online sources.

This module provides functionality to search and download metadata including
album art, artist information, and track details from various online sources
like MusicBrainz, Cover Art Archive, and Last.fm.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import quote, urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from core.config import get_config
from core.logging import get_logger

logger = get_logger(__name__)


class MetadataFetcher:
    """Fetches metadata and album art from online sources."""
    
    # Rate limiting: MusicBrainz allows 1 request per second
    _last_request_time = 0.0
    _min_request_interval = 1.0
    
    def __init__(self):
        """Initialize the metadata fetcher."""
        self.config = get_config()
        self.cache_dir = self.config.cache_dir / 'metadata_cache'
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # User agent for API requests (required by MusicBrainz)
        self.user_agent = f"MusicPlayer/1.0 (https://github.com/yourusername/musicplayer)"
    
    def fetch_metadata(
        self,
        title: Optional[str] = None,
        artist: Optional[str] = None,
        album: Optional[str] = None,
        duration: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch metadata from online sources.
        
        Args:
            title: Track title
            artist: Artist name
            album: Album name
            duration: Track duration in seconds
            
        Returns:
            Dictionary with metadata including album_art_path, or None if not found
        """
        # Build search query
        if not title and not artist:
            logger.warning("Cannot fetch metadata: need at least title or artist")
            return None
        
        # Check cache first
        cache_key = self._generate_cache_key(title, artist, album)
        cached = self._load_from_cache(cache_key)
        if cached:
            logger.debug("Using cached metadata for %s - %s", artist, title)
            return cached
        
        # Rate limiting
        self._wait_for_rate_limit()
        
        # Try MusicBrainz first (most reliable)
        metadata = self._fetch_from_musicbrainz(title, artist, album, duration)
        
        if not metadata:
            # Fallback to Last.fm
            metadata = self._fetch_from_lastfm(title, artist, album)
        
        if not metadata:
            # Fallback to iTunes Search API
            metadata = self._fetch_from_itunes(title, artist, album)
        
        # Cache the result
        if metadata:
            self._save_to_cache(cache_key, metadata)
        
        return metadata
    
    def fetch_album_art(
        self,
        artist: Optional[str] = None,
        album: Optional[str] = None,
        mbid: Optional[str] = None
    ) -> Optional[str]:
        """
        Fetch album art from Cover Art Archive or other sources.
        
        Args:
            artist: Artist name
            album: Album name
            mbid: MusicBrainz release ID (most reliable)
            
        Returns:
            Path to downloaded album art file, or None if not found
        """
        if not mbid and (not artist or not album):
            return None
        
        # Check cache
        cache_key = f"art_{hashlib.md5(f'{artist}_{album}_{mbid}'.encode()).hexdigest()}"
        cached_path = self.config.album_art_cache_dir / f"{cache_key}.jpg"
        if cached_path.exists():
            logger.debug("Using cached album art for %s - %s", artist, album)
            return str(cached_path)
        
        # Try Cover Art Archive if we have MBID
        if mbid:
            art_path = self._fetch_from_cover_art_archive(mbid, cache_key)
            if art_path:
                return art_path
        
        # Try Last.fm for album art
        if artist and album:
            art_path = self._fetch_art_from_lastfm(artist, album, cache_key)
            if art_path:
                return art_path
        
        # Try iTunes for album art
        if artist and album:
            art_path = self._fetch_art_from_itunes(artist, album, cache_key)
            if art_path:
                return art_path
        
        return None
    
    def _fetch_from_musicbrainz(
        self,
        title: Optional[str],
        artist: Optional[str],
        album: Optional[str],
        duration: Optional[float]
    ) -> Optional[Dict[str, Any]]:
        """Fetch metadata from MusicBrainz API."""
        try:
            # Build search query
            query_parts = []
            if title:
                query_parts.append(f'recording:"{title}"')
            if artist:
                query_parts.append(f'artist:"{artist}"')
            if album:
                query_parts.append(f'release:"{album}"')
            
            query = ' AND '.join(query_parts)
            url = f"https://musicbrainz.org/ws/2/recording/?query={quote(query)}&fmt=json&limit=5"
            
            request = Request(url)
            request.add_header('User-Agent', self.user_agent)
            
            with urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode())
                
                if not data.get('recordings'):
                    return None
                
                # Find best match
                best_match = None
                best_score = 0
                
                for recording in data['recordings']:
                    score = 0
                    
                    # Check title match
                    if title and recording.get('title', '').lower() == title.lower():
                        score += 10
                    elif title and title.lower() in recording.get('title', '').lower():
                        score += 5
                    
                    # Check artist match
                    if recording.get('artist-credit'):
                        for artist_credit in recording['artist-credit']:
                            if artist and artist.lower() in artist_credit.get('name', '').lower():
                                score += 10
                    
                    # Check duration match (within 5 seconds)
                    if duration and recording.get('length'):
                        rec_duration = recording['length'] / 1000.0  # Convert ms to seconds
                        if abs(rec_duration - duration) < 5:
                            score += 5
                    
                    if score > best_score:
                        best_score = score
                        best_match = recording
                
                if not best_match or best_score < 5:
                    return None
                
                # Extract metadata
                metadata = {
                    'title': best_match.get('title'),
                    'artist': None,
                    'album': None,
                    'mbid': best_match.get('id'),
                    'release_mbid': None,
                }
                
                # Get artist
                if best_match.get('artist-credit'):
                    artists = [ac.get('name', '') for ac in best_match['artist-credit']]
                    metadata['artist'] = ', '.join(artists) if artists else None
                
                # Get release (album) info
                if best_match.get('releases'):
                    release = best_match['releases'][0]
                    metadata['album'] = release.get('title')
                    metadata['release_mbid'] = release.get('id')
                
                # Fetch album art using release MBID
                if metadata['release_mbid']:
                    art_path = self.fetch_album_art(
                        artist=metadata['artist'],
                        album=metadata['album'],
                        mbid=metadata['release_mbid']
                    )
                    if art_path:
                        metadata['album_art_path'] = art_path
                
                return metadata
                
        except (URLError, HTTPError, json.JSONDecodeError, KeyError, TimeoutError) as e:
            logger.debug("MusicBrainz fetch failed: %s", e)
            return None
    
    def _fetch_from_lastfm(
        self,
        title: Optional[str],
        artist: Optional[str],
        album: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Fetch metadata from Last.fm API (no API key required for basic info)."""
        try:
            # Last.fm API doesn't require key for track.getInfo, but we'll use a simple search
            # For full API access, you'd need an API key
            if not title or not artist:
                return None
            
            # Use Last.fm's track.getInfo endpoint (requires API key for full access)
            # For now, we'll use it primarily for album art
            # This is a simplified version - full implementation would use API key
            
            metadata = {
                'title': title,
                'artist': artist,
                'album': album,
            }
            
            # Try to get album art
            if artist and album:
                art_path = self._fetch_art_from_lastfm(artist, album, None)
                if art_path:
                    metadata['album_art_path'] = art_path
            
            return metadata if metadata.get('album_art_path') else None
            
        except Exception as e:
            logger.debug("Last.fm fetch failed: %s", e)
            return None
    
    def _fetch_from_itunes(
        self,
        title: Optional[str],
        artist: Optional[str],
        album: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Fetch metadata from iTunes Search API."""
        try:
            # Build search query
            search_terms = []
            if artist:
                search_terms.append(artist)
            if title:
                search_terms.append(title)
            
            if not search_terms:
                return None
            
            query = ' '.join(search_terms)
            url = f"https://itunes.apple.com/search?{urlencode({'term': query, 'media': 'music', 'limit': 5})}"
            
            with urlopen(url, timeout=10) as response:
                data = json.loads(response.read().decode())
                
                if not data.get('results'):
                    return None
                
                # Find best match
                best_match = None
                best_score = 0
                
                for result in data['results']:
                    score = 0
                    
                    if title and title.lower() in result.get('trackName', '').lower():
                        score += 10
                    if artist and artist.lower() in result.get('artistName', '').lower():
                        score += 10
                    if album and album.lower() in result.get('collectionName', '').lower():
                        score += 5
                    
                    if score > best_score:
                        best_score = score
                        best_match = result
                
                if not best_match or best_score < 10:
                    return None
                
                metadata = {
                    'title': best_match.get('trackName') or title,
                    'artist': best_match.get('artistName') or artist,
                    'album': best_match.get('collectionName') or album,
                }
                
                # Get album art
                art_url = best_match.get('artworkUrl100') or best_match.get('artworkUrl60')
                if art_url:
                    # Replace with higher resolution (600x600)
                    art_url = art_url.replace('100x100', '600x600').replace('60x60', '600x600')
                    art_path = self._download_image(art_url, f"itunes_{hashlib.md5(f'{artist}_{album}'.encode()).hexdigest()}")
                    if art_path:
                        metadata['album_art_path'] = art_path
                
                return metadata
                
        except (URLError, HTTPError, json.JSONDecodeError, KeyError, TimeoutError) as e:
            logger.debug("iTunes fetch failed: %s", e)
            return None
    
    def _fetch_from_cover_art_archive(self, mbid: str, cache_key: str) -> Optional[str]:
        """Fetch album art from Cover Art Archive."""
        try:
            url = f"https://coverartarchive.org/release/{mbid}/front-500"
            
            request = Request(url)
            request.add_header('User-Agent', self.user_agent)
            
            with urlopen(request, timeout=10) as response:
                if response.status == 200:
                    art_path = self.config.album_art_cache_dir / f"{cache_key}.jpg"
                    with open(art_path, 'wb') as f:
                        f.write(response.read())
                    logger.info("Downloaded album art from Cover Art Archive")
                    return str(art_path)
            
            return None
            
        except (URLError, HTTPError, TimeoutError) as e:
            logger.debug("Cover Art Archive fetch failed: %s", e)
            return None
    
    def _fetch_art_from_lastfm(self, artist: str, album: str, cache_key: Optional[str]) -> Optional[str]:
        """Fetch album art from Last.fm."""
        try:
            # Last.fm image URLs (public, no API key needed for images)
            # Format: http://ws.audioscrobbler.com/2.0/?method=album.getinfo&api_key=YOUR_API_KEY&artist=ARTIST&album=ALBUM
            # But we can construct image URLs directly from their CDN
            # This is a simplified approach - for production, use their API
            
            # Last.fm uses a hash-based URL system, but we can try a direct approach
            # Note: This might not always work, but it's worth trying
            artist_clean = quote(artist.lower().replace(' ', '+'))
            album_clean = quote(album.lower().replace(' ', '+'))
            
            # Try different image sizes
            for size in ['large', 'extralarge', 'mega']:
                # This is a simplified approach - actual Last.fm requires API calls
                # For now, we'll skip Last.fm direct image fetching
                pass
            
            return None
            
        except Exception as e:
            logger.debug("Last.fm art fetch failed: %s", e)
            return None
    
    def _fetch_art_from_itunes(self, artist: str, album: str, cache_key: str) -> Optional[str]:
        """Fetch album art from iTunes."""
        try:
            query = f"{artist} {album}"
            url = f"https://itunes.apple.com/search?{urlencode({'term': query, 'media': 'music', 'limit': 1})}"
            
            with urlopen(url, timeout=10) as response:
                data = json.loads(response.read().decode())
                
                if data.get('results'):
                    result = data['results'][0]
                    art_url = result.get('artworkUrl100') or result.get('artworkUrl60')
                    if art_url:
                        # Get higher resolution
                        art_url = art_url.replace('100x100', '600x600').replace('60x60', '600x600')
                        return self._download_image(art_url, cache_key)
            
            return None
            
        except (URLError, HTTPError, json.JSONDecodeError, TimeoutError) as e:
            logger.debug("iTunes art fetch failed: %s", e)
            return None
    
    def _download_image(self, url: str, cache_key: str) -> Optional[str]:
        """Download an image from URL and save to cache."""
        try:
            request = Request(url)
            request.add_header('User-Agent', self.user_agent)
            
            with urlopen(request, timeout=10) as response:
                if response.status == 200:
                    art_path = self.config.album_art_cache_dir / f"{cache_key}.jpg"
                    with open(art_path, 'wb') as f:
                        f.write(response.read())
                    logger.info("Downloaded album art from %s", url)
                    return str(art_path)
            
            return None
            
        except (URLError, HTTPError, TimeoutError) as e:
            logger.debug("Image download failed: %s", e)
            return None
    
    def _generate_cache_key(self, title: Optional[str], artist: Optional[str], album: Optional[str]) -> str:
        """Generate a cache key from metadata."""
        key_str = f"{title or ''}_{artist or ''}_{album or ''}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _load_from_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Load metadata from cache."""
        cache_file = self.cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return None
        return None
    
    def _save_to_cache(self, cache_key: str, metadata: Dict[str, Any]):
        """Save metadata to cache."""
        cache_file = self.cache_dir / f"{cache_key}.json"
        try:
            with open(cache_file, 'w') as f:
                json.dump(metadata, f)
        except IOError as e:
            logger.warning("Failed to save metadata cache: %s", e)
    
    def _wait_for_rate_limit(self):
        """Wait if necessary to respect rate limits."""
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        
        if time_since_last < self._min_request_interval:
            sleep_time = self._min_request_interval - time_since_last
            time.sleep(sleep_time)
        
        self._last_request_time = time.time()


# Convenience function
def fetch_metadata(
    title: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    duration: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """Fetch metadata from online sources."""
    fetcher = MetadataFetcher()
    return fetcher.fetch_metadata(title, artist, album, duration)


