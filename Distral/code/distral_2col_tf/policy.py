import numpy as np
import tensorflow as tf
from collections import deque
import random
from tqdm import tqdm
from ops import conv2d, linear, clipped_error
from functools import reduce
import gym
from gym import spaces
import time

# 如何优化pi0
# 初始化策略pi0
# 然后初始化pii的q网络，用q和pi0表示pii，
# pii的动作，通过pii的策略选择出来，
# 计算出pi0策略下选择所有pii动作的概率，然后最大化它来优化pi0

try:
  from scipy.misc import imresize
except:
  import cv2
  imresize = cv2.resize

scale = 10

ENV_NAME = "Breakout-v4"
GAMMA = 0.9
REPLAY_BUFFER_SIZE = 100 * scale
BATCH_SIZE = 2
EPSILON = 0.01
HIDDEN_UNITS = 512

learning_rate = 0.00025
learning_rate_minimum = 0.00025
learning_rate_decay = 0.96
learning_rate_decay_step = 5 * scale

episodes = 3000
test_episodes = 10
steps = 300
test_steps = 300


class Policy:
    """Output action"""
    def __init__(self, action_dim, n_model, alpha, beta, sess=tf.InteractiveSession()):
        self.sess = sess
        self.n_model = n_model
        self.action_dim = action_dim    # action space of env

        self.replay_buffer = deque()    # buffer
        self.replay_buffer_size = REPLAY_BUFFER_SIZE
        self.batch_size = BATCH_SIZE

        self.episodes = episodes
        self.test_episodes = test_episodes
        self.episode_steps = steps
        self.test_episode_steps = test_steps

        self.gamma = GAMMA
        self.alpha = alpha
        self.beta = beta

        self.writer = tf.summary.FileWriter("./logs/")

        self.initializer = tf.truncated_normal_initializer(0, 0.02)
        self.activation_fn = tf.nn.relu

        self.w = {}     # 记录权重

        # build dqn model
        with tf.variable_scope('prediction'):
            # 1.use to select action model
            reuse = False
            self.state = tf.placeholder('float32', [None, 84, 84, 3], name='s')
            self.l1, self.w['l1_w'], self.w['l1_b'] = conv2d(self.state, 5, [2, 2], [1, 1],
                                                             initializer=self.initializer,
                                                             activation_fn=self.activation_fn,
                                                             name='l1', reuse=reuse)
            self.l2, self.w['l2_w'], self.w['l2_b'] = conv2d(self.l1, 10, [3, 3], [1, 1],
                                                             initializer=self.initializer,
                                                             activation_fn=self.activation_fn,
                                                             name='l2', reuse=reuse)
            self.l3, self.w['l3_w'], self.w['l3_b'] = conv2d(self.l2, 10, [3, 3], [1, 1],
                                                             initializer=self.initializer,
                                                             activation_fn=self.activation_fn,
                                                             name='l3', reuse=reuse)
            shape = self.l3.get_shape().as_list()
            self.l3_flat = tf.reshape(self.l3, [-1, reduce(lambda x, y: x * y, shape[1:])])
            # fc layers
            self.q, self.w['l4_w'], self.w['l4_b'] = linear(self.l3_flat, self.action_dim, name='q', reuse=reuse)
            self.action = tf.nn.log_softmax(self.q)     # output a softmax, stochastic policy

            # 2.use to optimize
            self.loss = 0.0
            n = self.n_model
            # list of placeholder
            self.states = [tf.placeholder('float32', [None, 84, 84, 3], name='s_t') for _ in range(n)]
            self.action_one_hot = [tf.placeholder("float", [None, self.action_dim], name="action") for _ in range(n)]
            self.next_state = [tf.placeholder('float32', [None, 84, 84, 3], name='s_t_1') for _ in range(n)]
            self.reward = [tf.placeholder('float32', [None, ], name='reward') for _ in range(n)]
            self.done = [tf.placeholder('bool', [None, ], name='done') for _ in range(n)]
            self.times = [tf.placeholder('float32', [None, ], name='timesteps') for _ in range(n)]

            reuse = True
            self.cur_loss_list = []     # help debug
            self.prob_list = []
            self.action_list = []
            self.q_list = []
            for i in range(self.n_model):
                self.l1, self.w['l1_w'], self.w['l1_b'] = conv2d(self.states[i], 5, [2, 2], [1, 1], initializer=self.initializer,
                                                                 activation_fn=self.activation_fn,
                                                                 name='l1', reuse=reuse)
                self.l2, self.w['l2_w'], self.w['l2_b'] = conv2d(self.l1, 10, [3, 3], [1, 1], initializer=self.initializer,
                                                                 activation_fn=self.activation_fn,
                                                                 name='l2', reuse=reuse)
                self.l3, self.w['l3_w'], self.w['l3_b'] = conv2d(self.l2, 10, [3, 3], [1, 1], initializer=self.initializer,
                                                                 activation_fn=self.activation_fn,
                                                                 name='l3', reuse=reuse)
                shape = self.l3.get_shape().as_list()
                self.l3_flat = tf.reshape(self.l3, [-1, reduce(lambda x, y: x * y, shape[1:])])
                # fc layers
                self.q, self.w['l4_w'], self.w['l4_b'] = linear(self.l3_flat, self.action_dim, name='q', reuse=reuse)
                # output a softmax, stochastic policy [0.x, ..., 0.x, ..., 0.x]
                self.action2 = tf.nn.softmax(self.q)

                # one hot action, [0, ..., 1, ..., 0]
                one_hot_actions = self.action_one_hot[i]
                # 计算出pi0策略下选择pii动作的概率pi(a|s)
                prob = tf.boolean_mask(self.action2, one_hot_actions)
                cur_loss = tf.reduce_sum(tf.pow(self.gamma, self.times[i]) * tf.log(prob))
                self.q_list.append(self.q)
                self.action_list.append(self.action2)
                self.prob_list.append(prob)
                self.cur_loss_list.append(cur_loss)
            self.loss -= cur_loss
        # optimizer
        with tf.variable_scope('optimizer'):
            self.global_step = tf.Variable(0, trainable=False)
            self.learning_rate = learning_rate
            self.learning_rate_step = tf.placeholder('int64', None, name='learning_rate_step')
            self.learning_rate_decay_step = learning_rate_decay_step
            self.learning_rate_decay = learning_rate_decay
            self.learning_rate_minimum = learning_rate_minimum
            self.learning_rate_op = tf.maximum(
                    self.learning_rate_minimum,
                    tf.train.exponential_decay(self.learning_rate,
                                               self.learning_rate_step,
                                               self.learning_rate_decay_step,
                                               self.learning_rate_decay,
                                               staircase=True)
                    )
            self.optimizer = tf.train.RMSPropOptimizer(
                    self.learning_rate_op, momentum=0.95, epsilon=0.01).minimize(self.loss)

    def add_models(self, models):
        self.models = models

    def experience(self, state, action, reward, next_state, done, time):
        one_hot_action = np.zeros(self.action_dim)
        one_hot_action[action] = 1
        self.replay_buffer.append((state, one_hot_action, reward, next_state, done, time))
        if len(self.replay_buffer) > self.replay_buffer_size:
            self.replay_buffer.popleft()

    def select_action(self, state):
        action = self.sess.run(self.action, feed_dict={self.state: state})
        return action

    def optimize_step(self, policy_step):
        state = []
        action = []
        reward = []
        next_state = []
        done = []
        times = []
        for i, model in enumerate(self.models):
            size_to_sample = np.minimum(self.batch_size, len(model.replay_buffer))
            batch = random.sample(model.replay_buffer, size_to_sample)

            state.append(np.array([data[0] for data in batch]))
            action.append(np.array([data[1] for data in batch]))
            next_state.append(np.array([data[3] for data in batch]))
            reward.append(np.array([data[2] for data in batch]))
            done.append(np.array([data[4] for data in batch]))
            times.append(np.array([data[5] for data in batch]))

        feed_dictionary = {}
        for k, v in zip(self.states, state):
            feed_dictionary[k] = v
        for k, v in zip(self.action_one_hot, action):
            feed_dictionary[k] = v
        for k, v in zip(self.reward, reward):
            feed_dictionary[k] = v.reshape(-1)
        for k, v in zip(self.next_state, next_state):
            feed_dictionary[k] = v
        for k, v in zip(self.done, done):
            feed_dictionary[k] = v
        for k, v in zip(self.times, times):
            feed_dictionary[k] = v.reshape(-1)
        feed_dictionary[self.learning_rate_step] = policy_step
        loss, _, loss_list, prob_list, action_list, q_list = self.sess.run(
            [self.loss, self.optimizer,
             self.cur_loss_list, self.prob_list,
             self.action_list, self.q_list],
            feed_dict=feed_dictionary
        )

        return loss
