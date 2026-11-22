from dataclasses import dataclass, field
from typing import List

from lightcycle.domain.feedback.review import (
    is_engine_marked,
    outstanding_reviews,
    outstanding_threads,
    review_gate_wanted,
    review_has_signal,
    thread_key,
)


def _folded(logins):
    return {login.casefold() for login in logins}


@dataclass(frozen=True)
class Roles:
    operators: frozenset
    bots: frozenset

    def is_trusted(self, author):
        who = author.casefold()
        return who in self.operators or who in self.bots

    def is_bot(self, author):
        return author.casefold() in self.bots


def roles_of(trusted, review_bots):
    trusted_set = _folded(trusted)
    bots = frozenset(_folded(review_bots) & trusted_set)
    return Roles(operators=frozenset(trusted_set - bots), bots=bots)


@dataclass(frozen=True)
class Sorted:
    inline: List = field(default_factory=list)
    review: List = field(default_factory=list)
    mention: List = field(default_factory=list)


def routed(top_level, inline, reviews, roles, mention_token):
    bot_inline = [c for c in inline if roles.is_bot(c.author)]
    bot_reviews = [r for r in reviews if roles.is_bot(r.author)]
    operator_inline = [
        c for c in inline
        if c.author.casefold() in roles.operators
        and not is_engine_marked(c)
        and mention_token and mention_token in c.body
    ]
    operator_reviews = [
        r for r in reviews
        if r.author.casefold() in roles.operators
        and not is_engine_marked(r)
        and review_has_signal(r)
        and mention_token and mention_token in r.body
    ]
    mentions = [
        c for c in top_level
        if roles.is_trusted(c.author)
        and not is_engine_marked(c)
        and mention_token and mention_token in c.body
    ]
    return Sorted(
        inline=outstanding_threads(bot_inline) + operator_inline,
        review=outstanding_reviews(bot_reviews, bot_inline, mention_token) + operator_reviews,
        mention=mentions,
    )


def gated(top_level, inline, reviews, roles):
    return Sorted(
        inline=[c for c in inline if not roles.is_trusted(c.author)],
        review=[
            r for r in reviews
            if not roles.is_trusted(r.author) and review_gate_wanted(r)
        ],
        mention=[c for c in top_level if not roles.is_trusted(c.author)],
    )


def thread_answered_by_operator(gate_comment, inline, roles):
    root = thread_key(gate_comment)
    return any(
        c.author.casefold() in roles.operators
        and not is_engine_marked(c)
        and thread_key(c) == root
        and c.created_at > gate_comment.created_at
        for c in inline
    )
