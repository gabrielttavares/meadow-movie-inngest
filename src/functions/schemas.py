from typing import TypedDict

from pydantic import BaseModel, EmailStr, Field


class MovieWatchedEventData(BaseModel):
    movie_title: str = Field(min_length=1)
    recipient_email: EmailStr


class OmdbMovieResponse(TypedDict, total=False):
    Title: str
    Year: str
    Rated: str
    Released: str
    Runtime: str
    Genre: str
    Director: str
    Plot: str
    Poster: str
    imdbRating: str
    imdbID: str
    Response: str
    Error: str
