import argparse
import os
import pickle as pk
from collections import defaultdict

import numpy as np
import torch
from scipy.special import softmax
from scipy.stats import entropy
from static_representations import handle_sentence
from tqdm import tqdm
from utils import CLUSTER_FOLDER_PATH, cosine_similarity_embeddings, evaluate_predictions, \
    cosine_similarity_embedding, tensor_to_numpy, MODELS


def probability_confidence(prob):
    return max(softmax(prob))


def rank_by_significance(embeddings, class_embeddings):
    similarities = cosine_similarity_embeddings(embeddings, class_embeddings)
    significance_score = [np.max(softmax(similarity)) for similarity in similarities]
    significance_ranking = {i: r for r, i in enumerate(np.argsort(-np.array(significance_score)))}
    return significance_ranking


def rank_by_relation(embeddings, class_embeddings):
    relation_score = cosine_similarity_embeddings(embeddings, [np.average(class_embeddings, axis=0)]).reshape((-1))
    relation_ranking = {i: r for r, i in enumerate(np.argsort(-np.array(relation_score)))}
    return relation_ranking


def mul(l):
    m = 1
    for x in l:
        m *= x + 1
    return m


def average_with_harmonic_series(representations):
    weights = [0.0] * len(representations)
    for i in range(len(representations)):
        weights[i] = 1. / (i + 1)
    return np.average(representations, weights=weights, axis=0)


def weights_from_ranking(rankings):
    if len(rankings) == 0:
        assert False
    if type(rankings[0]) == type(0):
        rankings = [rankings]
    rankings_num = len(rankings)
    rankings_len = len(rankings[0])
    assert all(len(rankings[i]) == rankings_len for i in range(rankings_num))
    total_score = []
    for i in range(rankings_len):
        total_score.append(mul(ranking[i] for ranking in rankings))

    total_ranking = {i: r for r, i in enumerate(np.argsort(np.array(total_score)))}
    if rankings_num == 1:
        assert all(total_ranking[i] == rankings[0][i] for i in total_ranking.keys())
    weights = [0.0] * rankings_len
    for i in range(rankings_len):
        weights[i] = 1. / (total_ranking[i] + 1)
    return weights


def weight_sentence_with_attention(vocab, tokenized_text, contextualized_word_representations, class_representations,
                                   attention_mechanism):
    assert len(tokenized_text) == len(contextualized_word_representations)

    contextualized_representations = []
    static_representations = []

    static_word_representations = vocab["static_word_representations"]
    word_to_index = vocab["word_to_index"]
    for i, token in enumerate(tokenized_text):
        if token in word_to_index:
            static_representations.append(static_word_representations[word_to_index[token]])
            contextualized_representations.append(contextualized_word_representations[i])
    if len(contextualized_representations) == 0:
        print("Empty Sentence (or sentence with no words that have enough frequency)")
        return np.average(contextualized_word_representations, axis=0)

    significance_ranking = rank_by_significance(contextualized_representations, class_representations)
    relation_ranking = rank_by_relation(contextualized_representations, class_representations)
    significance_ranking_static = rank_by_significance(static_representations, class_representations)
    relation_ranking_static = rank_by_relation(static_representations, class_representations)
    if attention_mechanism == "none":
        weights = [1.0] * len(contextualized_representations)
    elif attention_mechanism == "significance":
        weights = weights_from_ranking(significance_ranking)
    elif attention_mechanism == "relation":
        weights = weights_from_ranking(relation_ranking)
    elif attention_mechanism == "significance_static":
        weights = weights_from_ranking(relation_ranking)
    elif attention_mechanism == "relation_static":
        weights = weights_from_ranking(relation_ranking)
    elif attention_mechanism == "mixture":
        weights = weights_from_ranking((significance_ranking,
                                        relation_ranking,
                                        significance_ranking_static,
                                        relation_ranking_static))
    else:
        assert False
    return np.average(contextualized_representations, weights=weights, axis=0)


def weight_sentence(model,
                    vocab,
                    tokenization_info,
                    class_representations,
                    attention_mechanism,
                    layer
                    ):
    tokenized_text, tokenized_to_id_indicies, tokenids_chunks = tokenization_info
    contextualized_word_representations = handle_sentence(model, layer, tokenized_text, tokenized_to_id_indicies,
                                                          tokenids_chunks)
    document_representation = weight_sentence_with_attention(vocab, tokenized_text, contextualized_word_representations,
                                                             class_representations, attention_mechanism)
    return document_representation


def main(args):
    data_folder = os.path.join(CLUSTER_FOLDER_PATH, args.dataset_name)
    with open(os.path.join(data_folder, "dataset.pk"), "rb") as f:
        dataset = pk.load(f)
        class_names = dataset["class_names"]

    static_repr_path = os.path.join(data_folder, f"static_repr_lm-{args.lm_type}-{args.layer}.pk")
    with open(static_repr_path, "rb") as f:
        vocab = pk.load(f)
        static_word_representations = vocab["static_word_representations"]
        word_to_index = vocab["word_to_index"]
        vocab_words = vocab["vocab_words"]

    with open(os.path.join(data_folder, f"tokenization_lm-{args.lm_type}-{args.layer}.pk"), "rb") as f:
        tokenization_info = pk.load(f)["tokenization_info"]

    print("Finish reading data")

    print(class_names)
    class_representations = []
    all_class_words = []
    # print(cosine_similarity_embedding(static_word_representations[word_to_index["politics"]],
    #                                   static_word_representations[word_to_index["political"]]))
    # print(cosine_similarity_embedding(static_word_representations[word_to_index["politics"]],
    #                                   static_word_representations[word_to_index["politics,"]]))
    for cls in range(len(class_names)):
        class_words = [class_names[cls]]
        class_words_representations = [static_word_representations[word_to_index[class_names[cls]]]]
        masked_words = set()
        masked_words.add(class_names[cls])
        class_representation = average_with_harmonic_series(class_words_representations)
        # we run for one more iteration, since after the iterations we remove the last word (the last word will
        # either be the T + 1'th word, or the word that brought inconsistency)
        for t in range(1, args.T + 1):
            cosine_similarities = cosine_similarity_embeddings(static_word_representations,
                                                               [class_representation]).squeeze()
            highest_similarity = -1.0
            highest_similarity_word_index = -1
            lowest_masked_words_similarity = 1.0
            for i, word in enumerate(vocab_words):
                if word not in masked_words:
                    if cosine_similarities[i] > highest_similarity:
                        highest_similarity = cosine_similarities[i]
                        highest_similarity_word_index = i
                else:
                    lowest_masked_words_similarity = min(lowest_masked_words_similarity, cosine_similarities[i])
            # the topmost t words are no longer the t words in class_words
            if lowest_masked_words_similarity < highest_similarity:
                break
            class_words.append(vocab_words[highest_similarity_word_index])
            class_words_representations.append(static_word_representations[highest_similarity_word_index])
            masked_words.add(vocab_words[highest_similarity_word_index])
            class_representation = average_with_harmonic_series(class_words_representations)
        class_words = class_words[: -1]
        class_words_representations = class_words_representations[: -1]
        print(len(class_words), len(class_words_representations))
        class_representation = average_with_harmonic_series(class_words_representations)
        class_representations.append(class_representation)
        print(class_words)
        all_class_words.append(class_words)

    class_representations = np.array(class_representations)
    model_class, tokenizer_class, pretrained_weights = MODELS[args.lm_type]
    model = model_class.from_pretrained(pretrained_weights, output_hidden_states=True)
    model.eval()
    model.cuda()
    document_representations = []
    for i, _tokenization_info in tqdm(enumerate(tokenization_info), total=len(tokenization_info)):
        document_representation = weight_sentence(model,
                                                  vocab,
                                                  _tokenization_info,
                                                  class_representations,
                                                  args.attention_mechanism,
                                                  args.layer)
        document_representations.append(document_representation)
    document_representations = np.array(document_representations)
    print("Finish getting document representations")
    with open(os.path.join(data_folder,
                           f"document_repr_lm-{args.lm_type}-{args.layer}-{args.attention_mechanism}-{args.T}.pk"),
              "wb") as f:
        pk.dump({
            "all_class_words": all_class_words,
            "class_representations": class_representations,
            "document_representations": document_representations,
        }, f, protocol=4)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset_name", type=str, required=True)
    parser.add_argument("--random_state", type=int, default=42)
    parser.add_argument("--lm_type", type=str, default='bbu')
    parser.add_argument("--layer", type=int, default=12)
    parser.add_argument("--T", type=int, default=100)
    parser.add_argument("--attention_mechanism", type=str, default="mixture")

    args = parser.parse_args()
    print(vars(args))
    main(args)