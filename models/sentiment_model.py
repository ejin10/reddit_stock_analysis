# Sentiment Analysis Model from https://www.kaggle.com/arunmohan003/sentiment-analysis-using-lstm-pytorch

from utils.sentiment_util import tokenize
import torch
import torch.nn as nn
import numpy as np # linear algebra
import pandas as pd # data processing, CSV file I/O (e.g. pd.read_csv)
import torch


class MovementPredictor(nn.Module):
    """
    Full model for predicting stock movements.
    """
    def __init__(self, vocab_size, embedding_dim, hidden_dim, n_layers, bidirectional, dropout, pad_idx, alpha):
        self.sentiment_analysis = SentimentLSTM(vocab_size, embedding_dim, hidden_dim, n_layers, 
                                                bidirectional, dropout, pad_idx)
        self.out = OutputLayer(hidden_dim, hidden_dim, alpha)

    def forward(self, converted_text, multimodal_data):
        return self.out(self.sentiment_analysis(converted_text), multimodal_data)


class SentimentLSTM(nn.Module):
    def __init__(self, vocab_size, embedding_dim, hidden_dim, n_layers, 
                 bidirectional, dropout, pad_idx):
        """
        Define the layers of the module.

        vocab_size - vocabulary size
        embedding_dim - size of the dense word vectors
        hidden_dim - size of the hidden states
        output_dim - number of classes
        n_layers - number of multi-layer RNN
        bidirectional - boolean - use both directions of LSTM
        dropout - dropout probability
        pad_idx -  string representing the pad token
        """
        
        super().__init__()

        # 1. Feed the tweets in the embedding layer
        # padding_idx set to not learn the emedding for the <pad> token - irrelevant to determining sentiment
        self.embedding = nn.Embedding(vocab_size, embedding_dim, padding_idx = pad_idx)

        # 2. LSTM layer
        # returns the output and a tuple of the final hidden state and final cell state
        self.encoder = nn.LSTM(embedding_dim, 
                               hidden_dim, 
                               num_layers=n_layers,
                               bidirectional=bidirectional,
                               dropout=dropout)
        
        # 3. Fully-connected layer
        # Final hidden state has both a forward and a backward component concatenated together
        # The size of the input to the nn.Linear layer is twice that of the hidden dimension size
        self.predictor = nn.Linear(hidden_dim*2, hidden_dim)

        # Initialize dropout layer for regularization
        self.dropout = nn.Dropout(dropout)
      
    def forward(self, text, text_lengths):
        """
        The forward method is called when data is fed into the model.

        text - [tweet length, batch size]
        text_lengths - lengths of tweet
        """
        
        # embedded = [sentence len, batch size, emb dim]
        embedded = self.dropout(self.embedding(text))    

        # Pack the embeddings - cause RNN to only process non-padded elements
        # Speeds up computation
        packed_embedded = nn.utils.rnn.pack_padded_sequence(embedded, text_lengths.cpu())

        # output of encoder
        packed_output, (hidden, cell) = self.encoder(packed_embedded)

        # unpack sequence - transform packed sequence to a tensor
        output, output_lengths = nn.utils.rnn.pad_packed_sequence(packed_output)

        # output = [sentence len, batch size, hid dim * num directions]
        # output over padding tokens are zero tensors
        
        # hidden = [num layers * num directions, batch size, hid dim]
        # cell = [num layers * num directions, batch size, hid dim]
        
        # Get the final layer forward and backward hidden states  
        # concat the final forward and backward hidden layers and apply dropout
        hidden = self.dropout(torch.cat((hidden[-2,:,:], hidden[-1,:,:]), dim = 1))

        # hidden = [batch size, hid dim * num directions]

        return self.predictor(hidden)

class OutputLayer(nn.Module):
    """
    Two-stack of fully-connected output layers with 5 neurons. 
    To be used after sentiment analysis.
    """
    def __init__(self, input_size, hidden_size, alpha):
        self.model = nn.Sequential(
            nn.Linear(input_size, hidden_size),
            nn.ELU(alpha),
            nn.Linear(hidden_size, 5),
            nn.Softmax()
        )

    def forward(self, sentiment_output, y):
        # sentiment_output - output from sentiment analysis model
        # y - other input
        x = torch.cat(sentiment_output, y, dim=1)
        return self.model(x)