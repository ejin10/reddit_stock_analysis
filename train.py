from matplotlib.pyplot import uninstall_repl_displayhook
import torch
import torch.nn as nn
import torchtext
import csv 
from util import *
from models.sentiment_model import MovementPredictor
from sentiment_util import evaluate
from torchtext.legacy import data
import spacy
import torch.optim as optim
import torch.optim.lr_scheduler as sched
from torchtext.vocab import GloVe
import torch.nn.functional as F
import pdb


# def data_preprocess(csv_file):
#     data = torch.tensor(())
#     glove = GloVe(cache='.', name='6B')
#     with open(csv_file) as f:
#         reader = csv.reader(f, delimiter=',')
#         for row in reader:
#             # Convert data into word embeddings (PyTorch tensor).
#             text = row[:-4][0]
#             text = text.split(', ')
#             embed = []
#             for word in text:
#                 word = glove[word]
#                 embed.append(word)
#
#             # max_vocab_size = 287799
#
#             # TEXT -> WORD EMBEDDING
#             word_embedding = None
#             row_data = torch.cat((word_embedding, torch.tensor(row[-3:])), dim=0)
#             data = torch.cat((data, row_data), dim=0)
#     f.close()
#     pass
#
#     # data.shape = (N, word_embedding_size + 3 (1 for upvotes - downvotes, 1 for change in the last 7 days, label (next 7 days)))
#     idxs = torch.randperm(data.shape[0])
#     data = data[idxs, :]
#     train_size = data.shape[0] * 0.8
#     val_size = data.shape[0] * 0.1
#     test_size = data.shape[0] - train_size - val_size
#     train_split, val_split, test_split = torch.split(data, [train_size, val_size, test_size], dim=0)
#
#     return train_split, val_split, test_split


def create_csv():
    with open('removed_characters.csv') as in_file:
        with open('data_text.csv', 'w') as text_file:
            with open('data_other.csv', 'w') as other_file:
                reader = csv.reader(in_file, delimiter=',')
                writer_1 = csv.writer(text_file)
                writer_2 = csv.writer(other_file)
                for row in reader:
                    text = row[0].split(', ')
                    text = ' '.join(text)
                    text = [text]
                    other = row[-3:-1]
                    label = 1 - float(row[-1])
                    # Strong buy
                    if label >= .03:
                        label = 1
                    # Buy
                    elif .01 < label < .03:
                        label = 2
                    # Hold
                    elif -.01 <= label <= .01:
                        label = 3
                    # Sell
                    elif -.01 > label > -.03:
                        label = 4
                    else:
                        label = 5
                    other.extend([label])
                    writer_1.writerow(text)
                    writer_2.writerow(other)
    in_file.close()


def data_preprocess(max_vocab_size, device, batch_size):
    spacy.load("en_core_web_sm")

    TEXT = data.Field(tokenize='spacy', lower=True, include_lengths=True)
    UPVOTE = data.LabelField(dtype=torch.float)
    CHANGE = data.LabelField(dtype=torch.float)
    LABEL = data.LabelField(dtype=torch.float)

    # Map data to fields
    fields_text = [('text', TEXT), ('upvote', UPVOTE), ('change', CHANGE), ('label', LABEL)]

    # Apply field definition to create torch dataset
    dataset = data.TabularDataset(
        path="removed_characters.csv",
        format="CSV",
        fields=fields_text,
        skip_header=False)


    # Split data into train, test, validation sets
    (train_data, test_data, valid_data) = dataset.split(split_ratio=[0.8, 0.1, 0.1])

    print("Number of train data: {}".format(len(train_data)))
    print("Number of test data: {}".format(len(test_data)))
    print("Number of validation data: {}".format(len(valid_data)))

    # unk_init initializes words in the vocab using the Gaussian distribution
    TEXT.build_vocab(train_data,
                     max_size=max_vocab_size,
                     vectors="glove.6B.100d")

    # build vocab - convert words into integers
    UPVOTE.build_vocab(train_data)
    CHANGE.build_vocab(train_data)
    LABEL.build_vocab(train_data)

    train_iterator, valid_iterator, test_iterator = data.BucketIterator.splits(
        (train_data, valid_data, test_data),
        device=device,
        batch_size=batch_size,
        sort_key=lambda x: len(x.text),
        sort_within_batch=True)

    return train_iterator, valid_iterator, test_iterator


def main():
    create_csv()
    pdb.set_trace()
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    train = True
    batch_size = 128
    hidden_size = 200
    drop_prob = 0.2
    learning_rate = 1e-3
    num_epochs = 100
    save_dir = None # TODO: SET PATH.
    log_dir = None # TODO: SET PATH
    beta1, beta2 = 0.9, 0.999 # for Adam
    alpha = 0.2 # for ELU
    max_grad_norm = None # TODO: ?? WHAT IS THIS
    print_every = 1000
    # create_csv()

    # Initialize model.
    model = MovementPredictor(
        vocab_size=None, # TODO
        embedding_dim=None, # TODO
        hidden_dim=hidden_size,
        n_layers=None, # TODO
        bidirectional=True,
        dropout=drop_prob,
        pad_idx=None, # TODO
        alpha=alpha
    )
    device, gpu_ids = util.get_available_devices()
    model = nn.DataParallel(model, gpu_ids)

    train_iterator, valid_iterator, test_iterator = data_preprocess(25000, device, batch_size)

    # Initialize optimizer and scheduler.
    optimizer = optim.Adam(model.parameters, lr=learning_rate, betas=(beta1, beta2))
    #scheduler = sched.LambdaLR(optimizer, lambda s: 1.)

    iter = 0

    # Training Loop
    if train:
        for epoch in range(num_epochs):
            with torch.enable_grad():
                for vector in train_iterator:
                    optimizer.zero_grad()
                    # Grab labels.
                    target = torch.zeros((5,))
                    target[train_iterator[:, -1]] = 1
                    # Grab other data for multimodal sentiment analysis.
                    multimodal_data = train_iterator[:, -3:-2] # Upvotes + past week change
                    # Apply model
                    y = model(vector[:, :-4], multimodal_data)
                    target = target.to(device) # TODO: Unsure if this line is needed?
                    loss = nn.BCEWithLogitsLoss(y, target)
                    loss_val = loss.item()

                    # Backward
                    loss.backward()
                    nn.utils.clip_grad_norm_(model.parameters(), max_grad_norm)
                    optimizer.step()
                    #scheduler.step(step // batch_size)
                    if iter % print_every == 0:
                        print('Epoch:{:.4}, Iter: {:.4}, Loss:{:.4}'.format(iter, iter, loss.item()))


                    # TODO: Print + Log (not sure if needed rn)
                torch.save(model, save_dir)    
                if steps_till_eval == 0:
                    print("evaluating on dev split...")
                    loss_val, accuracy = evaluate(model, data=valid_iterator, criterion=nn.BCEWithLogitsLoss())
                    print("dev loss: ", loss_val, "dev accuracy: ", accuracy)
                    steps_till_eval = 3
                
    else: 
        # testing case
        print("testing data, loading from path" + save_dir + " ...")
        model = torch.load(save_dir)
        loss_val, accuracy = evaluate(model, test_iterator, criterion=nn.BCEWithLogitsLoss())
        print("test loss: ", loss_val, "test accuracy: ", accuracy)

    pdb.set_trace()


if __name__=="__main__":
    main()
