import asyncio
import time
from random import randint
from typing import Callable, Literal, Union, Optional, List, Dict, TYPE_CHECKING

from karmakaze import Sanitise

if TYPE_CHECKING:
    from aiohttp import ClientSession

__all__ = ["Api", "SORT_CRITERION", "TIMEFRAME", "TIME_FORMAT"]


SORT_CRITERION = Literal["controversial", "new", "top", "best", "hot", "rising", "all"]
TIMEFRAME = Literal["hour", "day", "week", "month", "year", "all"]
TIME_FORMAT = Literal["concise", "locale"]


class Api:
    """Represents the Knew Karma API and provides methods for getting various data from the Reddit API."""

    def __init__(self, headers: Optional[Dict] = None):
        self._headers = headers
        self._sanitise = Sanitise()

    @staticmethod
    def endpoint(
        kind: Literal[
            "base",
            "user",
            "users",
            "subreddit",
            "subreddits",
            "reddit_status",
            "reddit_status_components",
            "username_available",
        ]
    ) -> str:
        """
        A static method that contains endpoints for the specified `kind` of data.

        :param kind: Kind of data to get endpoint from.
        :type kind: Literal[str]
        :return: An endpoint of the specified `kind`.
        :rtype: str
        """
        base = "https://www.reddit.com"
        endpoint_map = {
            "base": base,
            "user": f"{base}/user",
            "users": f"{base}/users",
            "subreddit": f"{base}/r",
            "subreddits": f"{base}/subreddits",
            "reddit_status": "https://www.redditstatus.com/api/v2/status.json",
            "reddit_status_components": "https://www.redditstatus.com/api/v2/components.json",
            "username_available": f"{base}/api/username_available.json",
        }

        return endpoint_map.get(kind)

    async def send_request(
        self, session: ClientSession, endpoint: str, params: Optional[Dict] = None
    ) -> Union[Dict, List, bool, None]:
        """
        Asynchronously sends a GET request to the specified API endpoint and returns JSON or list response.

        :param session: An `aiohttp.ClientSession` for making the HTTP request.
        :type session: aiohttp.ClientSession
        :param endpoint: The API endpoint to fetch data from.
        :type endpoint: str
        :param params: A dictionary containing requests parameters. Defaults to None.
        :type params: Dict
        :return: JSON data as a dictionary or list or a boolean value. Raises an exception if fetching fails.
        :rtype: Union[Dict, List, bool]
        :raise Exception: If any is encountered.
        """

        try:
            async with session.get(
                url=endpoint, headers=self._headers, params=params
            ) as response:
                response.raise_for_status()
                response_data: Union[Dict, List] = await response.json()
                return response_data

        except Exception as error:
            raise error

    async def _paginate_items(
        self,
        session: ClientSession,
        sanitiser: Callable,
        limit: int,
        **kwargs,
    ) -> List[Dict]:
        """
        Asynchronously fetches and processes data in a paginated manner
        from a specified endpoint until the specified limit
        of items is reached or there are no more items to fetch. It uses a specified processing function
        to handle the data from each request, ensuring no duplicates are returned.

        :param session: An Aiohttp session to use for the request.
        :type session: aiohttp.ClientSession
        :param sanitiser: A callable used to sanitise response data.
        :type sanitiser: Callable
        :param limit: Maximum number of results to return.
        :type limit: int
        :return: A list of dict objects, each containing paginated data.
        :rtype: List[Dict]
        """

        status = kwargs.get("status")

        # Initialise an empty list to store all items across paginated requests.
        all_items: List = []
        # Initialise the ID of the last item fetched to None (used for pagination).
        last_item_id = None

        params: Dict = kwargs.get("params")

        # Continue fetching data until the limit is reached or no more items are available.
        while len(all_items) < limit:
            # Make an asynchronous request to the endpoint.
            response = await self.send_request(
                session=session,
                endpoint=kwargs.get("endpoint"),
                params=(
                    params.update({"after": last_item_id, "count": len(all_items)})
                    if last_item_id
                    else params
                ),
            )

            # If the request is for post comments, handle the response accordingly.
            if kwargs.get("is_comments_from_a_post"):
                items = []  # Initialise a list to store fetched items.
                more_items_ids = []  # Initialise a list to store IDs from "more" items.

                # Iterate over the children in the response to extract comments or "more" items.
                for item in response[1].get("data").get("children"):
                    if self._sanitise.kind(item) == "t1":
                        sanitised_item = sanitiser(item)
                        # If the item is a comment (kind == "t1"), add it to the items list.
                        items.append(sanitised_item)
                    elif self._sanitise.kind(item) == "more":
                        # If the item is of kind "more", extract the IDs for additional comments.
                        more_items_ids.extend(item)

                # If there are more items to fetch (kind == "more"), make additional requests.
                if more_items_ids:
                    await self._paginate_more_items(
                        session=session,
                        fetched_items=items,
                        more_items_ids=more_items_ids,
                        endpoint=kwargs.get("endpoint"),
                    )

            # If not handling comments, simply extract the items from the response.
            items = sanitiser(response)

            # If no items are found, break the loop as there's nothing more to fetch.
            if not items:
                break

            # Determine how many more items are needed to reach the limit.
            items_to_limit = limit - len(all_items)

            # Add the processed items to the all_items list, up to the specified limit.
            all_items.extend(items[:items_to_limit])

            # Update the last_item_id to the ID of the last fetched item for pagination.
            last_item_id = (
                self._sanitise.pagination_id(response=response[1])
                if kwargs.get("is_post_comments")
                else self._sanitise.pagination_id(response=response)
            )

            # If we've reached the specified limit, break the loop.
            if len(all_items) == limit:
                break

            # Introduce a random sleep duration between 1 and 5 seconds to avoid rate-limiting.
            sleep_duration = randint(1, 5)

            # If a status object is provided, use it to display a countdown timer.
            if status:
                await self._pagination_countdown_timer(
                    status=status,
                    duration=sleep_duration,
                    current_count=len(all_items),
                    overall_count=limit,
                )
            else:
                # Otherwise, just sleep for the calculated duration.
                await asyncio.sleep(sleep_duration)

        # Return the list of all fetched and processed items.
        return all_items

    async def _paginate_more_items(
        self,
        session: ClientSession,
        more_items_ids: List[str],
        endpoint: str,
        fetched_items: List[Dict],
    ):
        for more_id in more_items_ids:
            # Construct the endpoint for each additional comment ID.
            more_endpoint = f"{endpoint}&comment={more_id}"
            # Make an asynchronous request to fetch the additional comments.
            more_response = await self.send_request(
                session=session, endpoint=more_endpoint
            )
            # Extract the items (comments) from the response.
            more_items, _ = self._sanitise.comments(
                response=more_response[1].get("data", {}).get("children", [])
            )

            # Add the fetched items to the main items list.
            fetched_items.extend(more_items)

    @staticmethod
    async def _pagination_countdown_timer(
        duration: int, current_count: int, overall_count: int, **kwargs
    ):
        """
        A static method handles the live countdown during pagination, updating the status bar with the remaining time.

        :param duration: The duration for which to run the countdown.
        :type duration: int
        :param current_count: Current number of items fetched.
        :type current_count: int
        :param overall_count: Overall number of items to fetch.
        :type overall_count: int
        """

        status = kwargs.get("status")

        end_time: float = time.time() + duration
        while time.time() < end_time:
            remaining_time: float = end_time - time.time()
            remaining_seconds: int = int(remaining_time)
            remaining_milliseconds: int = int(
                (remaining_time - remaining_seconds) * 100
            )

            countdown_text: str = (
                f"[cyan]{current_count}[/] (of [cyan]{overall_count}[/]) items retrieved so far. "
                f"Resuming in [cyan]{remaining_seconds}.{remaining_milliseconds:02}[/] seconds"
            )

            (
                status.update(countdown_text)
                if status
                else print(countdown_text.strip("[,],/,cyan"))
            )
            await asyncio.sleep(0.01)  # Sleep for 10 milliseconds

    async def check_reddit_status(
        self, session: ClientSession, **kwargs
    ) -> Union[List[Dict], None]:
        """
        Asynchronously checks Reddit API and infrastructure status.

        :param session: An `aiohttp.ClientSession` for making the HTTP request.
        :type session: aiohttp.ClientSession
        """

        notify = kwargs.get("notify")
        status = kwargs.get("status")

        if status:
            status.update(f"Checking Reddit [bold]API/Infrastructure[/] status")

        status_response: Dict = await self.send_request(
            endpoint=self.endpoint(kind="reddit_status"), session=session
        )

        indicator = status_response.get("status").get("indicator")
        description = status_response.get("status").get("description")
        if description:
            if indicator == "none":

                notify.ok(description) if notify else print(description)
            else:
                status_message = f"{description} ([yellow]{indicator}[/])"
                (
                    notify.warning(status_message)
                    if notify
                    else print(status_message.strip("[,],/,yellow"))
                )  # TODO: remove the colours in print

                if status:
                    status.update("Getting status components")

                status_components: Dict = await self.send_request(
                    endpoint=self.endpoint(kind="reddit_status_components"),
                    session=session,
                )

                if isinstance(status_components, Dict):
                    components: List[Dict] = status_components.get("components")

                    return components

    async def get_entity(
        self,
        session: ClientSession,
        kind: Literal["comment", "post", "subreddit", "user", "wikipage"],
        **kwargs,
    ) -> Dict:
        """
        Asynchronously gets data from the specified entity.

        :param session: An `aiohttp.ClientSession` for making the HTTP request.
        :type session: aiohttp.ClientSession
        :param kind: The type of entity to get data from
        :type kind: str
        :return: A dictionary containing a specified entity's data.
        :rtype: Dict
        """
        status = kwargs.get("status")
        username = kwargs.get("username")
        subreddit = kwargs.get("subreddit")
        post_id = kwargs.get("id")
        comment_id = kwargs.get("comment_id")

        entity_mapping = {
            """
            "comment": {
                "endpoint": f"{self.endpoint(kind='subreddit')}",
                "sanitiser": lambda data: self._sanitise.comment(data),
            },
            """
            "post": {
                "endpoint": f"{self.endpoint(kind='subreddit')}/{subreddit}"
                f"/comments/{post_id}.json",
                "sanitiser": lambda data: self._sanitise.post(data),
            },
            "user": {
                "endpoint": f"{self.endpoint(kind='user')}/{username}/about.json",
                "sanitiser": lambda data: self._sanitise.subreddit_or_user(data),
            },
            "subreddit": {
                "endpoint": f"{self.endpoint(kind='subreddit')}/{subreddit}/about.json",
                "sanitiser": lambda data: self._sanitise.subreddit_or_user(data),
            },
            "wikipage": {
                "endpoint": f"{self.endpoint(kind='subreddit')}/{subreddit}/wiki/{kwargs.get('page_name')}.json",
                "sanitiser": lambda data: self._sanitise.wiki_page(data),
            },
        }

        if status:
            status.update(
                f"Retrieving {kind} data",
            )

        endpoint = entity_mapping.get(kind).get("endpoint")
        sanitiser = entity_mapping.get(kind).get("sanitiser")

        response = await self.send_request(endpoint=endpoint, session=session)
        sanitised_response = sanitiser(response)

        return sanitised_response

    async def get_posts_or_comments(
        self,
        session: ClientSession,
        kind: Literal[
            "best",
            "controversial",
            "front_page",
            "new",
            "popular",
            "rising",
            "posts_from_a_subreddit",
            "search_from_a_subreddit",
            "posts_from_a_user",
            "overview_of_a_user",
            "comments_from_a_user",
            "comments_from_a_post",
        ],
        limit: int,
        timeframe: TIMEFRAME = "all",
        sort: SORT_CRITERION = "all",
        **kwargs,
    ) -> List[Dict]:
        """
        Asynchronously gets a specified number of posts or comments, with a specified sorting criterion, from the specified source.

        :param session: An `aiohttp.ClientSession` for making the HTTP request.
        :type session: aiohttp.ClientSession
        :param kind: The kind of posts to be fetched.
        :type kind: str
        :param limit: Maximum number of posts to get.
        :type limit: int
        :param sort: Posts' sort criterion.
        :type sort: str
        :param timeframe: Timeframe from which to get posts.
        :type timeframe: Literal
        :return: A list of dictionaries, each containing post data.
        :rtype: List[Dict]
        """

        status = kwargs.get("status")
        username = kwargs.get("username")
        subreddit = kwargs.get("subreddit")

        posts_or_comments_mapping = {
            "best": f"{self.endpoint(kind='base')}/r/{kind}.json",
            "controversial": f"{self.endpoint(kind='base')}/r/{kind}.json",
            "front_page": f"{self.endpoint(kind='base')}/.json",
            "new": f"{self.endpoint(kind='base')}/new.json",
            "popular": f"{self.endpoint(kind='base')}/r/{kind}.json",
            "rising": f"{self.endpoint(kind='base')}/r/{kind}.json",
            "posts_from_a_subreddit": f"{self.endpoint(kind='subreddit')}/{subreddit}.json",
            "posts_from_a_user": f"{self.endpoint(kind='user')}/{username}/submitted.json",
            "overview_of_a_user": f"{self.endpoint(kind='user')}/{username}/overview.json",
            "comments_from_a_user": f"{self.endpoint(kind='user')}/{username}/comments.json",
            "comments_from_a_post": f"{self.endpoint(kind='subreddit')}/{subreddit}"
            f"/comments/{kwargs.get('id')}.json",
            "search_from_a_subreddit": f"{self.endpoint(kind='subreddit')}/{subreddit}"
            f"/search.json",
        }

        if status:
            status.update(f"Retrieving {limit} {kind} (posts/comments)")

        endpoint = posts_or_comments_mapping.get(kind)
        params = {"limit": limit, "sort": sort, "t": timeframe, "raw_json": 1}
        params.update(
            {"q": kwargs.get("query"), "restrict_sr": 1}
            if kind == "search_from_a_subreddit"
            else {}
        )

        sanitiser = (
            self._sanitise.comments
            if kind in ["user_comments", "user_overview", "post_comments"]
            else self._sanitise.posts
        )

        posts = await self._paginate_items(
            session=session,
            endpoint=endpoint,
            params=params,
            status=status,
            sanitiser=sanitiser,
            limit=limit,
            is_comments_from_a_post=True if kind == "comments_from_a_post" else False,
        )

        return posts

    async def get_subreddits(
        self,
        session: ClientSession,
        kind: Literal["all", "default", "new", "popular", "user_moderated"],
        limit: int,
        timeframe: TIMEFRAME = "all",
        **kwargs,
    ) -> Union[List[Dict], Dict]:
        """
        Asynchronously gets the specified type of subreddits.

        :param session: An `aiohttp.ClientSession` for making the HTTP request.
        :type session: aiohttp.ClientSession
        :param kind: The kind of subreddits to get.
        :type kind: str
        :param limit: Maximum number of subreddits to return.
        :type limit: int
        :param timeframe: Timeframe from which to get subreddits.
        :type timeframe: Literal
        :return: A list of dictionaries, each containing subreddit data,
            or a single dictionary containing subreddit data.
        :rtype: Union[List[Dict], Dict]
        """

        status = kwargs.get("status")
        subreddits_mapping = {
            "all": f"{self.endpoint(kind='subreddits')}.json",
            "default": f"{self.endpoint(kind='subreddits')}/default.json",
            "new": f"{self.endpoint(kind='subreddits')}/new.json",
            "popular": f"{self.endpoint(kind='subreddits')}/popular.json",
            "user_moderated": f"{self.endpoint(kind='user')}/{kwargs.get('username')}/moderated_subreddits.json",
        }

        if status:
            status.update(f"Retrieving {limit} {kind} subreddits")

        endpoint = subreddits_mapping.get(kind, "")
        params = {"raw_json": 1}

        if kind == "user_moderated":
            subreddits = await self.send_request(
                endpoint=endpoint,
                session=session,
            )
        else:
            params.update({"limit": limit, "t": timeframe})
            subreddits = await self._paginate_items(
                session=session,
                params=params,
                endpoint=endpoint,
                sanitiser=self._sanitise.subreddits_or_users,
                limit=limit,
                status=status,
            )

        return subreddits

    async def get_users(
        self,
        session: ClientSession,
        kind: Literal["all", "popular", "new"],
        limit: int,
        timeframe: TIMEFRAME = "all",
        **kwargs,
    ) -> List[Dict]:
        """
        Asynchronously gets the specified type of subreddits.

        :param kind: The kind of users to get.
        :type kind: str
        :param limit: Maximum number of users to return.
        :type limit: int
        :param timeframe: Timeframe from which to get users.
        :type timeframe: Literal
        :param session: An `aiohttp.ClientSession` for making the HTTP request.
        :type session: aiohttp.ClientSession
        :return: A list of dictionaries, each containing user data.
        :rtype: List[Dict]
        """

        status = kwargs.get("status")
        users_mapping = {
            "all": f"{self.endpoint(kind='users')}.json",
            "new": f"{self.endpoint(kind='users')}/new.json",
            "popular": f"{self.endpoint(kind='users')}/popular.json",
        }

        if status:
            status.update(f"Retrieving {limit} {kind} users")

        endpoint = users_mapping.get(kind)
        params = {
            "limit": limit,
            "t": timeframe,
        }

        users = await self._paginate_items(
            session=session,
            params=params,
            endpoint=endpoint,
            sanitiser=self._sanitise.subreddits_or_users,
            limit=limit,
            status=status,
        )

        return users

    async def search_entities(
        self,
        session: ClientSession,
        kind: Literal["users", "subreddits", "posts"],
        query: str,
        limit: int,
        sort: SORT_CRITERION = "all",
        **kwargs,
    ) -> List[Dict]:
        """
        Asynchronously searches specified entities that match the specified query.

        :param session: An `aiohttp.ClientSession` for making the HTTP request.
        :type session: aiohttp.ClientSession
        :param kind: The kind of entity to search for.
        :type kind: Literal[str]
        :param query: Search query.
        :type query: str
        :param limit: Maximum number of results to get.
        :type limit: int
        :param sort: Posts' sort criterion.
        :type sort: str
        :return: A list of dictionaries, each containing search result data.
        :rtype: List[Dict]
        """

        status = kwargs.get("status")
        search_mapping = {
            "posts": self.endpoint(kind="base"),
            "subreddits": self.endpoint(kind="subreddits"),
            "users": self.endpoint(kind="users"),
        }

        endpoint = search_mapping.get(kind)
        endpoint += f"/search.json"
        params = {"q": query, "limit": limit, "sort": sort, "raw_json": 1}

        sanitiser = (
            self._sanitise.posts
            if kind == "posts"
            else self._sanitise.subreddits_or_users
        )

        if status:
            status.update(f"Searching for '{query}' in {limit} {kind}")

        search_results = await self._paginate_items(
            session=session,
            params=params,
            endpoint=endpoint,
            status=status,
            sanitiser=sanitiser,
            limit=limit,
        )

        return search_results


# -------------------------------- END ----------------------------------------- #
