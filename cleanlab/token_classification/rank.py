# Copyright (C) 2017-2022  Cleanlab Inc.
# This file is part of cleanlab.
#
# cleanlab is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# cleanlab is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with cleanlab.  If not, see <https://www.gnu.org/licenses/>.

"""
Methods to rank and score sentences in a token classification dataset (text data), based on how likely they are to contain label errors.
"""

import pandas as pd
import numpy as np
from typing import List, Optional, Union, Tuple

from cleanlab.rank import get_label_quality_scores as main_get_label_quality_scores


def _softmin_sentence_score(
    token_scores: List[np.ndarray], temperature: float = 0.05
) -> np.ndarray:
    """
    sentence scoring using the "softmin" scoring method.

    Parameters
    ----------
    token_scores:
        token scores in nested list format, where `token_scores[i]` is a list of token scores of the i'th
        sentence

    temperature:
        temperature of the softmax function

    Returns
    ---------
    sentence_scores:
        np.array of shape `(N, )`, where `N` is the number of sentences. Contains score for each sentence.

    Examples
    ---------
    >>> from cleanlab.token_classification.rank import _softmin_sentence_score
    >>> token_scores = [[0.9, 0.6], [0.0, 0.8, 0.8], [0.8]]
    >>> _softmin_sentence_score(token_scores)
    array([6.00741787e-01, 1.80056239e-07, 8.00000000e-01])
    """
    if temperature == 0:
        return np.array([np.min(scores) for scores in token_scores])

    if temperature == np.inf:
        return np.array([np.mean(scores) for scores in token_scores])

    def softmax(scores: np.ndarray) -> np.ndarray:
        exp_scores = np.exp(scores / temperature)
        return exp_scores / np.sum(exp_scores)

    def fun(scores: np.ndarray) -> float:
        return np.dot(scores, softmax(1 - np.array(scores)))

    sentence_scores = list(map(fun, token_scores))
    return np.array(sentence_scores)


def get_label_quality_scores(
    labels: list,
    pred_probs: list,
    *,
    tokens: Optional[list] = None,
    token_score_method: str = "self_confidence",
    sentence_score_method: str = "min",
    sentence_score_kwargs: dict = {},
) -> Union[np.ndarray, Tuple[np.ndarray, list]]:
    """
    Returns overall quality scores for the labels in each sentence (as well as for the individual tokens' labels)
    This is a function to compute label-quality scores for token classification datasets, where lower scores
    indicate labels less likely to be correct.
    Score is between 0 and 1.
    1 - clean label (given label is likely correct).
    0 - dirty label (given label is likely incorrect).

    Parameters
    ----------
    labels:
        noisy token labels in nested list format, such that `labels[i]` is a list of token labels of the i'th
        sentence. For datasets with `K` classes, each label must be in 0, 1, ..., K-1. All classes must be present.
    pred_probs:
        list of np.arrays, such that `pred_probs[i]` is the model-predicted probabilities for the tokens in
        the i'th sentence, and has shape `(N, K)`. Each row of the matrix corresponds to a token `t` and contains
        the model-predicted probabilities that `t` belongs to each possible class, for each of the K classes. The
        columns must be ordered such that the probabilities correspond to class 0, 1, ..., K-1.

    tokens:
        tokens in nested list format, such that `tokens[i]` is a list of tokens for the i'th sentence. See return value
        `token_info` for more info.
    sentence_score_method: {"min", "softmin"}, default="min"
        sentence scoring method to aggregate token scores.
        - `min`: sentence score = minimum token label score of the sentence
        - `softmin`: sentence score = <s, softmax(1-s, t)>, where s denotes the token label scores of the sentence,
        and <a, b> == np.dot(a, b). The parameter `t` controls parameter of softmax, such that when t -> 0, the
        method approaches to `min`. This method is the "softer" version of `min`, which adds some minor weights to
        other scores.
    token_score_method: {"self_confidence", "normalized_margin", "confidence_weighted_entropy"}, default="self_confidence"
        label quality scoring method. See `cleanlab.rank.get_label_quality_scores` for more info.
    sentence_score_kwargs:
        keyword arguments for `sentence_score_method`. Supports keyword arguments when `sentence_score_method` is "softmin".
        See `cleanlab.token_classification.rank._softmin_sentence_score` for more info.
    Returns
    ----------
    sentence_scores:
        A vector of sentence scores between 0 and 1, where lower scores indicate sentence is more likely to contain at
        least one label issue.
    token_info:
        A list of pandas.Series, such that token_info[i] contains the
        token scores for the i'th sentence. If tokens are provided, the series is indexed by the tokens.

    Examples
    --------
    >>> import numpy as np
    >>> from cleanlab.token_classification.rank import get_label_quality_scores
    >>> labels = [[0, 0, 1], [0, 1]]
    >>> pred_probs = [
    ...     np.array([[0.9, 0.1], [0.7, 0.3], [0.05, 0.95]]),
    ...     np.array([[0.8, 0.2], [0.8, 0.2]]),
    ... ]
    >>> sentence_scores, token_info = get_label_quality_scores(labels, pred_probs)
    >>> sentence_scores
    array([0.7, 0.2])
    >>> token_info
    [0    0.90
    1    0.70
    2    0.95
    dtype: float64, 0    0.8
    1    0.2
    dtype: float64]
    """
    methods = ["min", "softmin"]
    assert sentence_score_method in methods, "Select from the following methods:\n%s" % "\n".join(
        methods
    )

    labels_flatten = np.array([l for label in labels for l in label])
    pred_probs_flatten = np.array([p for pred_prob in pred_probs for p in pred_prob])

    sentence_length = [len(label) for label in labels]

    def nested_list(x, sentence_length):
        i = iter(x)
        return [[next(i) for _ in range(length)] for length in sentence_length]

    token_scores = main_get_label_quality_scores(
        labels=labels_flatten, pred_probs=pred_probs_flatten, method=token_score_method
    )
    scores_nl = nested_list(token_scores, sentence_length)

    if sentence_score_method == "min":
        sentence_scores = np.array(list(map(np.min, scores_nl)))
    else:
        assert sentence_score_method == "softmin"
        temperature = sentence_score_kwargs.get("temperature", 0.05)
        sentence_scores = _softmin_sentence_score(scores_nl, temperature=temperature)

    if tokens:
        token_info = [pd.Series(scores, index=token) for scores, token in zip(scores_nl, tokens)]
    else:
        token_info = [pd.Series(scores) for scores in scores_nl]
    return sentence_scores, token_info


def issues_from_scores(
    sentence_scores: np.ndarray, token_scores: Optional[list] = None, threshold: float = 0.1
) -> Union[list, np.ndarray]:
    """
    Converts output from `get_label_quality_score` to list of issues. Only includes issues with label quality score
    lower than `threshold`. Issues are sorted by token label quality score in ascending order.

    Parameters
    ----------
    sentence_scores:
        np.array of shape `(N, )`, where `N` is the number of sentences.

    token_scores:
        token scores in nested list, such that `token_scores[i]` contains the tokens scores for the i'th sentence

    threshold:
        tokens (or sentences, if `token_scores` is not provided) with quality scores above the threshold are not
        included in the result.

    Returns
    ---------
    issues:
        list of tuples `(i, j)`, which indicates the j'th token of the i'th sentence, sorted by token label quality
        score. If `token_scores` is not provided, returns list of indices of sentences with label quality score below
        threshold.

    Examples
    --------
    >>> import numpy as np
    >>> from cleanlab.token_classification.rank import issues_from_scores
    >>> sentence_scores = np.array([0.1, 0.3, 0.6, 0.2, 0.05, 0.9, 0.8, 0.0125, 0.5, 0.6])
    >>> issues_from_scores(sentence_scores)
    array([7, 4])

    Changing the score threshold

    >>> issues_from_scores(sentence_scores, threshold=0.5)
    array([7, 4, 0, 3, 1])

    Providing token scores along with sentence scores finds issues at the token level

    >>> token_scores = [
    ...     [0.9, 0.6],
    ...     [0.0, 0.8, 0.8],
    ...     [0.8, 0.8],
    ...     [0.1, 0.02, 0.3, 0.4],
    ...     [0.1, 0.2, 0.03, 0.4],
    ...     [0.1, 0.2, 0.3, 0.04],
    ...     [0.1, 0.2, 0.4],
    ...     [0.3, 0.4],
    ...     [0.08, 0.2, 0.5, 0.4],
    ...     [0.1, 0.2, 0.3, 0.4],
    ... ]
    >>> issues_from_scores(sentence_scores, token_scores)
    [(1, 0), (3, 1), (4, 2), (5, 3), (8, 0)]
    """
    if token_scores:
        issues_with_scores = []
        for sentence_index, scores in enumerate(token_scores):
            for token_index, score in enumerate(scores):
                if score < threshold:
                    issues_with_scores.append((sentence_index, token_index, score))

        issues_with_scores = sorted(issues_with_scores, key=lambda x: x[2])
        issues = [(i, j) for i, j, _ in issues_with_scores]
        return issues

    else:
        ranking = np.argsort(sentence_scores)
        cutoff = 0
        while sentence_scores[ranking[cutoff]] < threshold and cutoff < len(ranking):
            cutoff += 1
        return ranking[:cutoff]
