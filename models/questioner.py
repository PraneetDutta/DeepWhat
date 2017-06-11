import torch
from torch.autograd import Variable
import torch.nn as nn
import torch.nn.functional as F

import vocab
import data


vocab_map = vocab.VocabMap()
vocab_size = vocab_map.vocab_size

RESNET_FEATURE_SIZE = 2048

class QuestionerNet(nn.Module):
    def __init__(self, vocab_size=vocab_size, token_embed_dim=64):
        super(QuestionerNet, self).__init__()
        
        self.token_embedding = nn.Embedding(
            num_embeddings=vocab_size,
            embedding_dim=token_embed_dim
        )
        
        self.encoder = nn.LSTM(
            input_size=RESNET_FEATURE_SIZE + token_embed_dim,
            hidden_size=vocab_size,
            num_layers=1,
            batch_first=True
        )
        
        self.optimizer = torch.optim.Adam(self.parameters())
        self.loss_fn = nn.CrossEntropyLoss()
        
    def forward(self, features, in_seq, h_0=None):
        in_embed = self.token_embedding(in_seq)
        
        features = features.unsqueeze(1)
        features_repeated = features.repeat(1, in_seq.size(1), 1)
        
        encoder_inputs = torch.cat([in_embed, features_repeated], 2)
        
        logits, h_n = self.encoder(encoder_inputs, h_0)
        return logits, h_n
        
    def sample(self, features, h_0=None, x_0=None, mode='greedy'):
        '''
        Eval time sample
        
        Parameters:
            features: Resnet features
            h_0: the hidden state returned at the end of the previous question,
                 or None if we're starting a game
            x_0: token ID for <start> or the previous answer, <Yes>/<No>/<N/A>
            mode: 'greedy', 'random' for random sample, or 'beam' for beam search
        '''
        utterance = []
        
        x, h = x_0, h_0
        
        if x is None:
            x = Variable(torch.LongTensor([[vocab_map.start]]).cuda(), volatile=True)
        
        while True:
            logits, h = self(features, x, h_0=h)
            probs = F.softmax(logits.view(-1, logits.size(-1)))
            # print(logits.size())
            # print(probs.size())
            prob, x = torch.max(probs, dim=1)
            print(prob)
            
            token_id = int(x.data.cpu().numpy().squeeze())
            utterance.append(token_id)
            if token_id == vocab_map.qmark or token_id == vocab_map.stop or len(utterance) >= data.MAX_TOKENS_PER_QUESTION:
                return utterance, h
    
    def train_step(self, features, in_seq, out_seq, seq_mask):
        logits, h_n = self(features, in_seq)
        # print(logits.max(dim=-1)[1][0, :3, :])
        #print(logits)
        
        # see: https://github.com/pytorch/pytorch/issues/764
        # and https://gist.github.com/jihunchoi/f1434a77df9db1bb337417854b398df1
        logits_flat = logits.contiguous().view(-1, logits.size(-1))
        #print(logits_flat)
        out_seq_flat = out_seq.view(-1, 1)
        #print(out_seq)
        #print(out_seq_flat)
        
        log_probs_flat = F.log_softmax(logits_flat)
        losses_flat = -torch.gather(log_probs_flat, dim=1, index=out_seq_flat)
        
        losses = losses_flat.view(*out_seq.size()) * seq_mask
        loss = losses.sum() / seq_mask.sum()
        
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        
        return loss
        