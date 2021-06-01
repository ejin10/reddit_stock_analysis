from matplotlib.pyplot import uninstall_repl_displayhook
import torch
import torch.nn as nn
import torchtext
import csv 
import util
from sentiment_util import evaluate
from models.sentiment_model import MovementPredictor
from torchtext.legacy import data
import spacy
import torch.optim as optim
import torch.optim.lr_scheduler as sched
from torchtext.vocab import GloVe
import torch.nn.functional as F
import pdb

TEXT = data.Field(tokenize='spacy', lower=True, include_lengths=True)
UPVOTE = data.LabelField(dtype=torch.float)
CHANGE = data.LabelField(dtype=torch.float)
LABEL = data.LabelField(dtype=torch.float)


def create_csv():
    with open('removed_characters.csv') as in_file:
        with open('removed_characters_buckets.csv', 'w') as out_file:
            reader = csv.reader(in_file, delimiter=',')
            writer = csv.writer(out_file)
            for row in reader:
                text = row[0].split(', ')
                text = ' '.join(text)
                row_data = [text]
                row_data.extend(row[-3:-1])
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
                row_data.append(label)
                writer.writerow(row_data)
    in_file.close()


def data_preprocess(max_vocab_size, device, batch_size):
    spacy.load("en_core_web_sm")

    # Map data to fields
    fields_text = [('text', TEXT), ('upvote', UPVOTE), ('change', CHANGE), ('label', LABEL)]

    # Apply field definition to create torch dataset
    dataset = data.TabularDataset(
        path="removed_characters_buckets.csv",
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
                     vectors="glove.6B.100d",
                     unk_init=torch.Tensor.normal_)

    # build vocab - convert words into integers
    UPVOTE.build_vocab(train_data)
    CHANGE.build_vocab(train_data)
    LABEL.build_vocab(train_data)

    train_iterator, valid_iterator, test_iterator = data.BucketIterator.splits(
        (train_data, valid_data, test_data),
        device=device,
        batch_size=batch_size,
        sort_key=lambda x: len(x.text),
        sort_within_batch=False)

    return train_iterator, valid_iterator, test_iterator


def main():
    create_csv()
    train = True
    batch_size = 128
    hidden_size = 256
    drop_prob = 0.5
    learning_rate = 1e-2
    num_epochs = 100
    beta1, beta2 = 0.9, 0.999 # for Adam
    alpha = 0.2 # for ELU
    max_grad_norm = 1.0
    print_every = 10
    save_dir = 'results/model.path_lr_{:.4}_drop_prob_{:.4}_alpha_{:.4}.tar'.format(learning_rate, drop_prob, alpha)

    device, gpu_ids = util.get_available_devices()

    train_iterator, valid_iterator, test_iterator = data_preprocess(25000, device, batch_size)

    # Initialize model.
    model = MovementPredictor(
        vocab_size=287799,
        embedding_dim=100,
        hidden_dim=hidden_size,
        n_layers=2,
        bidirectional=True,
        dropout=drop_prob,
        pad_idx=TEXT.vocab.stoi[TEXT.pad_token],
        alpha=alpha
    )

    model = nn.DataParallel(model, gpu_ids)

    # Initialize optimizer and scheduler.
    optimizer = optim.Adam(model.parameters(), lr=learning_rate, betas=(beta1, beta2))
    #scheduler = sched.LambdaLR(optimizer, lambda s: 1.)

    iter = 0
    steps_till_eval = 0

    # Training Loop
    if train:
        for epoch in range(num_epochs):
            with torch.enable_grad():
                for vector in train_iterator:
                    optimizer.zero_grad()
                    # Grab labels.
                    target = torch.zeros((batch_size, 5))
                    target[torch.arange(batch_size), vector.label.type(dtype=torch.int64)] = 1
                    # Grab other data for multimodal sentiment analysis.
                    multimodal_data = torch.cat((vector.upvote.unsqueeze(dim=1),
                                                 vector.change.unsqueeze(dim=1)), dim=1) # Upvotes + past week change
                    # Apply model
                    y = model(vector, multimodal_data)
                    target = target.to(device)
                    loss_function = nn.BCEWithLogitsLoss()
                    loss = loss_function(y, target)
                    loss_val = loss.item()

                    # Backward
                    loss.backward()
                    nn.utils.clip_grad_norm_(model.parameters(), max_grad_norm)
                    optimizer.step()
                    #scheduler.step(step // batch_size)
                    if iter % print_every == 0:
                        print('Epoch:{}, Iter: {}, Loss:{:.4}'.format(epoch, iter, loss.item()))
                    iter += 1

                    if iter == 10:
                        break

                torch.save(model, save_dir)
                if steps_till_eval % 3 == 0:
                    print("evaluating on dev split...")
                    loss_val, accuracy = evaluate(model, valid_iterator, device)
                    print("dev loss: ", loss_val, "dev accuracy: ", accuracy)
                    steps_till_eval += 1
                
    else: 
        # testing case
        print("testing data, loading from path" + save_dir + " ...")
        model = torch.load(save_dir)
        loss_val, accuracy = evaluate(model, test_iterator, criterion=nn.BCEWithLogitsLoss())
        print("test loss: ", loss_val, "test accuracy: ", accuracy)


if __name__=="__main__":
    main()
