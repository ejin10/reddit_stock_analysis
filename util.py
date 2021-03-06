import os
import torch
import numpy as np
import random
import ujson as json
from preprocessing import get_data, write_csv
import regex as re
import string


def get_tweets_change(filename):
    data = get_data(filename)
    num_data = len(data)
    tweets = [data[i][0] for i in range(num_data)]
    change = np.asarray([float(data[i][-1]) for i in range(num_data)])
    return tweets, change


def get_words(tweet):
    """Convert to lowercase and remove punctuation, articles and extra whitespace."""
    def remove_articles(text):
        regex = re.compile(r'\b(a|an|the|that|to|but|we|are|at|is|in|were|yourself|or|you|your|you.|me|their)\b', re.UNICODE)
        return re.sub(regex, ' ', text)

    def white_space_fix(text):
        return ' '.join(text.split())

    # def remove_punc(text):
    #     exclude = set(string.punctuation)
    #     return ''.join(ch for ch in text if ch not in exclude)

    def lower(text):
        return text.lower()

    return white_space_fix(remove_articles(lower(tweet))).split()

def get_available_devices():
    """Get IDs of all available GPUs.

    Returns:
        device (torch.device): Main device (GPU 0 or CPU).
        gpu_ids (list): List of IDs of all GPUs that are available.
    """
    gpu_ids = []
    if torch.cuda.is_available():
        gpu_ids += [gpu_id for gpu_id in range(torch.cuda.device_count())]
        device = torch.device(f'cuda:{gpu_ids[0]}')
        torch.cuda.set_device(device)
    else:
        device = torch.device('cpu')

    return device, gpu_ids

def create_dict(tweets, num_occur):
    temp = {}
    for tweet in tweets:
        words = set(get_words(tweet))
        for word in words:
            count = temp.get(word, 0) + 1
            temp[word] = count
    temp = {key: value for (key, value) in temp.items() if value >= num_occur}
    dict = {index: word for index, word in enumerate(temp)}
    return dict


def data_iter(batch_size, x, y):
    num_examples = len(x)
    indices = list(range(num_examples))
    random.shuffle(indices)
    for i in range(0, num_examples, batch_size):
        batch_indices = np.array(indices[i:min(i + batch_size, num_examples)])
        yield x[batch_indices], y[batch_indices]


def transform_text(tweets, dictionary):
        """Transform a list of text messages into a numpy array that contains the number of
        times each word of the vocabulary appears in each message.
        """
        n, d = len(tweets), len(dictionary)
        occur = np.zeros((n, d))

        for i in range(n):
            if i % 1000 == 0:
                print('Sample', i, 'out of', n)
            words = get_words(tweets[i])
            for index, word in dictionary.items():
                occur[i, index] = words.count(word)
        return occur


def write_json(filename, value):
    """Write the provided value as JSON to the given filename"""
    with open(filename, 'w') as f:
        json.dump(value, f)


def get_top_words(num_words, tweet_matrix, change, dict):
    """Returns list of words with highest expected percent change in price (in increasing order), given the word appears in a message
       num_words = number of top words to get
       tweet_matrix = np array where (i,j) entry corresponds to number
       of times the j-th word in the dictionary appears in the i-th tweet
       change = percent change in price
       dict = dictionary where key = column in tweet_matrix, value = word
    """
    expected = np.sum(tweet_matrix * change[:, np.newaxis], axis=0)
    top_words = np.argsort(expected)[-num_words:]
    top_words = [dict.get(i) for i in reversed(top_words)]
    return top_words


def create_buckets(y):
    y = np.where(y < -0.03, 5, y)
    y = np.where(y < -0.01, 4, y)
    y = np.where(y < 0.01, 3, y)
    y = np.where(y < 0.03, 2, y)
    y = np.where(y < 1, 1, y)

    return y.astype('int32')