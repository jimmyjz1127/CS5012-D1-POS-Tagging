from nltk import FreqDist, WittenBellProbDist
import os
import numpy as np 
import pandas 
import sys 
from treebanks import conllu_corpus, train_corpus, test_corpus
from math import exp, log
import re
import pprint
import json
from nltk.util import ngrams
from sys import float_info
from math import log, exp
import time 


class Tagger():
   
    def __init__(self, lang):
        self.min_log_prob = -float_info.max

        self.train_sents = conllu_corpus(train_corpus(lang))
        self.test_sents = conllu_corpus(test_corpus(lang))

        # pre-process train and test sentences 
        self.train_sents = self.preprocess_sentences(self.train_sents)
        self.test_sents =  self.preprocess_sentences(self.test_sents)

        # get set of all unique tags 
        self.tags = set([ tag for sentence in self.train_sents for ( _, tag) in sentence])
        self.words = set([w for sentence in self.train_sents for (w,_) in sentence])

        # get smoothed emission and transisions (bigram)
        self.emissions = self.init_smoothed_emission_dist(self.train_sents, self.tags)
        self.transitions = self.init_smoothed_transition_dist(self.train_sents)



    def preprocess_sentences(self, sentences):
        '''
            Takes corpus sentence in conllu form and adds start and end of sentence markers to each sentence
            Modifies each token into form  : (word, tag)

            Arguments 
                sentences : list of sentences in conllu form 
            Returns
                list of sentences of form : [[(word, tag)]]
        '''

        sents = [] # [(form, upos)]
        
        # Convert conllu format to tuples of form (id, word, tag)
        for sentence in sentences:  
            sent = [('<s>', 'START')]

            for token in sentence:
                sent.append((token['form'].lower(), token['upos']))

            sent.append(('</s>', 'END'))
            sents.append(sent)

        return sents

    def init_smoothed_emission_dist(self, sentences, tags):
        """
            Calculates smoothed distribution of emission probabilities P(word | tag)

            Arguments:
                sentences : list of sentences [[(word, tag)]]


            Returns : emission probability distribution (with Witten-Bell smoothing)
        """

        distribution = {}

        for tag in tags:
            words = [w for sentence in sentences for (w, t) in sentence if t == tag]
            distribution[tag] = WittenBellProbDist(FreqDist(words), bins=1e5)
    
        return distribution
    
    
    def init_smoothed_transition_dist(self, sentences):
        '''
            Calculates smoothed distribution of transition probabilities P( tag[i] | tag[i-1] )

            @param sentences : list of sentences [[(word, tag)]]
            @return : transition probability trellis (with witten-bell smoothing)
        '''
        bigrams = [] 

        for sentence in sentences:
            tags = [obj[1] for obj in sentence]
            bigrams += ngrams(tags, 2)
 
        transition_trellis = WittenBellProbDist(FreqDist(bigrams), bins=1e5)

        return transition_trellis

    def eager_tag(self, sentence):
        """ 
            Tags a sentence using eager algorithm

            @param sentence : sentence to tag in form of [(word, tag)]
            @returns : a new sentence list with predicted tags [(word, predicted tag)]
        """

        pred_sent = [sentence[0]] # initialize with start-of-sentence
        prev_tag='START'
        for token in sentence[1:]:
            word = token[0] # the word to predict tag for 

            # list of all possible (tag, emission_prob * transistion_prob) for the given word
            probs = [(tag, self.emissions[tag].logprob(word) + self.transitions.logprob((prev_tag, tag))) for tag in self.tags]

            # tag with highest probability 
            max_prob_tag = max(probs, key=lambda obj:obj[1])[0]

            pred_sent.append((word,max_prob_tag))
            prev_tag = max_prob_tag
            # NOTE : we are leaving out end-of-sentence marker
        pred_sent.append(sentence[-1])

        return pred_sent
        

    def viterbi_tag(self, sentence):
        """
            Tags a sentence using the viterbi algorithm 

            @param sentence : the sentence to tag in form [(word, tag)]
            @return : a new sentence list with predicted tags [(word, predicted tag)]
        """
        viterbi = []

        # Initliaize "viterbi[q,1] for all q"
        initial = {} 
        for tag in self.tags:
            initial[tag] = self.transitions.logprob(('START',tag)) + self.emissions[tag].logprob(sentence[1][0])
        viterbi.append(initial)

        # Intermediary "viterbi[q,i] for i=2,...,n"
        for i in range(2, len(sentence)):
            token = sentence[i][0]
            probs = {}

            for tag in self.tags:
                probs[tag] = max([viterbi[-1][prev_tag] + self.transitions.logprob((prev_tag,tag)) + self.emissions[tag].logprob(token) for prev_tag in self.tags])
            viterbi.append(probs)
        
        # Finish "viterbi[qf, n+1]"
        final = {}
        final['END'] = max([viterbi[-1][prev_tag] + self.transitions.logprob((prev_tag,'END')) for prev_tag in self.tags])
        viterbi.append(final)

        # Backtrack
        pred_sent = [("<s>", "START")]
        for i in range(1, len(sentence) - 1):
            v_col = viterbi[i - 1]
            max_tag = max(v_col.items(), key=lambda obj:obj[1])[0]
            pred_sent.append((sentence[i][0], max_tag))
        pred_sent.append(('</s>', 'END'))
    
        return pred_sent
    
    def forward_backward_tag(self, sentence):
        """
            Tags a sentence using the "individually most probable tag" method 

            @param sentence : the sentence to tag of form [(word, tag)] 
            @return : a new sentence list with predicted tags [(word, predicted tag)]
        """
        forward = []
        backward = []

        # INITIAL 
        # forward[q,1] for all q
        # backward[q,n] for all q
        initial_f = {}
        initial_b = {}
        
        for tag in self.tags:
            initial_f[tag] = self.transitions.logprob(('START', tag)) + self.emissions[tag].logprob(sentence[1][0])
            initial_b[tag] = self.transitions.logprob((tag, 'END'))
        forward.append(initial_f)
        backward.append(initial_b)

        # INTERMEDIARY 
        # forward[q,i] for i = 2,...,n and all q
        # backward[q,i] for i = n-1,...,1 and all q
        for i in range(2, len(sentence) - 1):
            intermed_f = {}
            intermed_b = {}
            token_f = sentence[i][0]
            token_b = sentence[len(sentence) - i][0]

            for tag in self.tags:
                inner_f = [forward[-1][prev_tag] + self.transitions.logprob((prev_tag, tag)) + self.emissions[tag].logprob(token_f) for prev_tag in self.tags]
                inner_b = [backward[-1][next_tag] + self.transitions.logprob((tag, next_tag)) + self.emissions[next_tag].logprob(token_b) for next_tag in self.tags]
                intermed_f[tag] = self.logsumexp(inner_f)
                intermed_b[tag] = self.logsumexp(inner_b)

            forward.append(intermed_f)
            backward.append(intermed_b)

        # FINAL
        # forward[qf, n+1] 
        # backward[q0, 0]
        final_f = {}
        final_b = {}
        final_f['END'] = self.logsumexp([forward[-1][prev_tag] + self.transitions.logprob((prev_tag, 'END')) for prev_tag in self.tags])
        final_b['START'] = self.logsumexp([backward[-1][next_tag] + self.transitions.logprob(('START', next_tag)) + self.emissions[next_tag].logprob(sentence[1][0]) for next_tag in self.tags])
        forward.append(final_f)
        backward.append(final_b)

        # reverse backwards matrix to align with forward matrix 
        backward.reverse() 

        # cut off columns for start and end of sentence markers 
        backward = backward[1:]
        forward = forward[:-1]  

        #BACK TRACK
        pred_sent = [("<s>", "START")]
        for i in range(0, len(sentence) - 2):
            f_col = forward[i]
            b_col = backward[i]
            combined = self.combine_dicts(f_col, b_col)
            max_tag = max(combined.items(), key = lambda obj:obj[1])[0]
            pred_sent.append((sentence[i + 1][0], max_tag))
        pred_sent.append(("</s>", "END"))
                
        return pred_sent

    def run(self, algo):
        """
            For applying an HMM tagging algorithm to all sentences of a the test corpus 

            @param algo : integer specifying which algorithm to use 
                1 : eager algorithm
                2 : viterbi algorithm
                3 : forward-back (individually most probable tag) algorithm

            @returns : the new list of sentences with predicted tags 
        """

        sentences = self.test_sents
        result = []
    
        if algo == 1:
            for sentence in sentences:
                result.append(self.eager_tag(sentence))
            return result
        elif algo == 2:
            for sentence in sentences:
                result.append(self.viterbi_tag(sentence))
            return result
        elif algo == 3:
            for sentence in sentences:
                result.append(self.forward_backward_tag(sentence))
            return result
        else :
            return None


    def combine_dicts(self, dict1, dict2):
        """
            For combining the values of two dictionaries into a single dictionary 
            (for combining forward and backward tables of forward-backward algorithm)

            @param dict1 : dictionary {String : Double}
            @param dict2 : dictionary {String : Double}
            @returns : combined dictionary {String : Double}
        """
        result = {}
        for key in dict1.keys():
            result[key] = dict1[key] + dict2[key]
        return result


    def logsumexp(self, vals):
        """
            For summing a list of log probabilities 

            @param vals : list of log probabilities [double]
            @returns : the log sum (double)
        """
        if len(vals) == 0:
            return self.min_log_prob
        m = max(vals)
        if m == self.min_log_prob:
            return self.min_log_prob
        else:
            return m + log(sum([exp(val - m) for val in vals]))

    def calc_accuracy(self, predictions):
        """
            Calculates the accuracy of an algorithm by comparing its predicted tags against actual tags 

            @param predictions : the sentences with predicted tags of form [[(word, tag)]]
            @returns : double representing (# of correct tags)/total
        """

        num_correct = 0.0
        total = 0.0

        for i in range(0, len(self.test_sents)):
            pred_sent = predictions[i]
            label_sent = self.test_sents[i]

            for j in range(0, len(label_sent)):
                pred_tag = pred_sent[j][1]
                label_tag = label_sent[j][1]

                if pred_tag == label_tag:
                    num_correct += 1.0

                total += 1.0
        return num_correct/total

def main():
    tagger = Tagger('en')

    result = tagger.run(1)

    print('Eager :', tagger.calc_accuracy(result))

    result = tagger.run(2)
    
    print('Viterbi :', tagger.calc_accuracy(result))

    result = tagger.run(3)

    print('F-B :', tagger.calc_accuracy(result))

    # sentence = [('<s>', 'START'), ('these', 'DET'), ('series', 'NOUN'), ('are', 'AUX'), ('represented', 'VERB'), ('by', 'ADP'), ('colored', 'ADJ'), ('data', 'NOUN'), ('markers', 'NOUN'), (',', 'PUNCT'), ('and', 'CCONJ'), ('their', 'PRON'), ('names', 'NOUN'), ('appear', 'VERB'), ('in', 'ADP'), ('the', 'DET'), ('chart', 'NOUN'), ('legend', 'NOUN'), ('.', 'PUNCT'), ('</s>', 'END')]

    # result = tagger.forward_backward_tag(sentence)

    # print(len(sentence))
    # print(len(result))

    # print(result)

    
    
if __name__ == '__main__':
    main()

    