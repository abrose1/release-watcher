"""Shared test fixtures — dummy taste profile data and mock API responses."""

DUMMY_CREATORS = [
    {"id": 1, "category": "music", "name": "Test Artist A", "tier": 1,
     "external_id": "spotify_id_aaa", "profile_score_at_sync": 95.0},
    {"id": 2, "category": "music", "name": "Test Artist B", "tier": 2,
     "external_id": "spotify_id_bbb", "profile_score_at_sync": 60.0},
    {"id": 3, "category": "book", "name": "Test Author A", "tier": 1,
     "external_id": "gbooksid_aaa", "profile_score_at_sync": 88.0},
    {"id": 4, "category": "book", "name": "Test Author B", "tier": 2,
     "external_id": "gbooksid_bbb", "profile_score_at_sync": 45.0},
]

DUMMY_TASTE_PROFILE_SLICE = {
    "top_music_artists": ["Test Artist A", "Test Artist B"],
    "top_book_authors": ["Test Author A"],
    "film_taste": "I like slow-burn thrillers and literary drama.",
}

MOCK_SPOTIFY_ALBUM = {
    "id": "album_123",
    "name": "Test Album",
    "release_date": "2026-04-01",
    "album_type": "album",
    "artists": [{"name": "Test Artist A"}],
    "external_urls": {"spotify": "https://open.spotify.com/album/album_123"},
}

MOCK_SPOTIFY_SINGLE = {
    "id": "single_456",
    "name": "Test Single",
    "release_date": "2026-04-15",
    "album_type": "single",
    "artists": [{"name": "Test Artist A"}],
    "external_urls": {"spotify": "https://open.spotify.com/album/single_456"},
}

MOCK_SPOTIFY_ALBUMS_RESPONSE = {
    "items": [MOCK_SPOTIFY_ALBUM],
    "total": 1,
}

MOCK_SPOTIFY_SINGLES_RESPONSE = {
    "items": [MOCK_SPOTIFY_SINGLE],
    "total": 1,
}

MOCK_SPOTIFY_TOKEN_RESPONSE = {
    "access_token": "test_access_token",
    "token_type": "Bearer",
    "expires_in": 3600,
}

MOCK_SPOTIFY_RECOMMENDATIONS = {
    "tracks": [
        {
            "id": "rec_track_1",
            "name": "Recommended Song",
            "artists": [{"name": "New Artist"}],
            "album": {"id": "rec_album_1", "name": "Rec Album"},
        }
    ]
}

MOCK_TMDB_TV_RESPONSE = {
    "seasons": [
        {
            "season_number": 3,
            "name": "Season 3",
            "air_date": "2026-03-15",
            "overview": "The third season",
        },
        {
            "season_number": 2,
            "name": "Season 2",
            "air_date": "2024-01-01",
            "overview": "The second season",
        },
    ]
}

MOCK_TMDB_MOVIES_RESPONSE = {
    "results": [
        {
            "id": 99999,
            "title": "Test Thriller",
            "release_date": "2026-05-01",
            "overview": "A slow-burn thriller",
            "genre_ids": [18, 53],
        }
    ]
}

MOCK_TMDB_SIMILAR_RESPONSE = {
    "results": [
        {
            "id": 88888,
            "name": "Similar Show",
            "first_air_date": "2026-03-01",
            "overview": "A similar TV show",
        }
    ]
}

MOCK_BOOKS_RESPONSE = {
    "items": [
        {
            "id": "book_789",
            "volumeInfo": {
                "title": "Test Novel",
                "authors": ["Test Author A"],
                "publishedDate": "2026-03-01",
                "description": "A test novel",
                "pageCount": 320,
                "infoLink": "https://books.google.com/books?id=book_789",
            },
        }
    ]
}

MOCK_BRAVE_SEARCH_RESPONSE = {
    "web": {
        "results": [
            {
                "title": "Test Article - New Album Review",
                "url": "https://example.com/review",
                "description": "A review of the new album",
            },
            {
                "title": "Artist Announces New Release",
                "url": "https://example.com/announcement",
                "description": "The artist has announced a new release",
            },
        ]
    }
}

MOCK_JUDGE_NOTIFY = {"notify": True, "reason": "Test reason", "best_link": "https://example.com/review"}
MOCK_JUDGE_SKIP = {"notify": False, "reason": "Not a genuine release", "best_link": ""}
