""" Written by Jonas Chan for the Udacity Machine Learning Course on the 3rd of March 2018 """

import os
import numpy as np
import random
import pandas as pd
from keras import layers, models, optimizers
from keras.layers.normalization import BatchNormalization
from quad_controller_rl import util
from keras import backend as K
from quad_controller_rl.agents.base_agent import BaseAgent
from collections import namedtuple
import h5py
Experience = namedtuple("Experience", field_names=["state", "action", "reward", "next_state", "done"])

class DDPG_Hover(BaseAgent):
    """Agent that searches for optimal policy using DDPG."""

    def __init__(self, task):
	
        # Save episode stats
        self.stats_filename = os.path.join(
            util.get_param('out'),
            "stats_{}.csv".format(util.get_timestamp()))  # path to CSV file
        self.stats_columns = ['episode', 'total_reward']  # specify columns to save
        self.episode_num = 1
        print("Saving stats {} to {}".format(self.stats_columns, self.stats_filename))  # [debug]

        # Save model weights to a file
        # Load/save parameters
        self.load_weights = True  # try to load weights from previously saved models
        self.save_weights_every = 1  # save weights every n episodes, None to disable
        self.model_dir = util.get_param('out')  # you can use a separate subdirectory for each task and/or neural net architecture
        self.model_name = "land"
        self.model_ext = ".h5"

        if self.load_weights or self.save_weights_every:
            self.actor_filename = os.path.join(self.model_dir,
                "{}_actor{}".format(self.model_name, self.model_ext))
            self.critic_filename = os.path.join(self.model_dir,
                "{}_critic{}".format(self.model_name, self.model_ext))
            print("Actor filename :", self.actor_filename)   #[debug]
            print("Critic filename:", self.critic_filename)  # [debug]

        # Task (environment) information
        self.task = task  # should contain observation_space and action_space
        #self.state_size = np.prod(self.task.observation_space.shape)
        self.state_size = 1
        self.state_range = self.task.observation_space.high - self.task.observation_space.low
        #self.action_size = np.prod(self.task.action_space.shape)
        self.action_size = 1
        self.action_range = self.task.action_space.high - self.task.action_space.low

        # Policy parameters
#        self.w = np.random.normal(
#            size=(self.state_size, self.action_size),  # weights for simple linear policy: state_space x action_space
#            scale=(self.action_range / (2 * self.state_size)).reshape(1, -1))  # start producing actions in a decent range

        # Score tracker and learning parameters
        self.best_w = None
        self.best_score = -np.inf
        self.noise_scale = 0.1

        # Episode variables
        self.episode = 0
        self.reset_episode_vars()

        # Actor (Policy) Model
#        self.action_low = self.task.action_space.low
#        self.action_high = self.task.action_space.high
        self.action_low = self.task.action_space.low[2:3]
        self.action_high = self.task.action_space.high[2:3]
        self.actor_local = Actor(self.state_size, self.action_size, self.action_low, self.action_high)
        self.actor_target = Actor(self.state_size, self.action_size, self.action_low, self.action_high)

        # Critic (Value) Model
        self.critic_local = Critic(self.state_size, self.action_size)
        self.critic_target = Critic(self.state_size, self.action_size)

        # Load pre-trained model weights, if available
        if self.load_weights and os.path.isfile(self.actor_filename):
            try:
                self.actor_local.model.load_weights(self.actor_filename)
                self.critic_local.model.load_weights(self.critic_filename)
                print("Model weights loaded from file!")  # [debug]
            except Exception as e:
                print("Unable to load model weights from file!")
                print("{}: {}".format(e.__class__.__name__, str(e)))

        if self.save_weights_every:
            print("Saving model weights", "every {} episodes".format(
                self.save_weights_every) if self.save_weights_every else "disabled")#[debug]

        # Initialize target model parameters with local model parameters
        self.critic_target.model.set_weights(self.critic_local.model.get_weights())
        self.actor_target.model.set_weights(self.actor_local.model.get_weights())

        # Noise process
        self.noise = OUNoise(self.action_size)

        # Replay memory
        self.buffer_size = 100000
        self.batch_size = 64
        self.memory = ReplayBuffer(self.buffer_size)

        # Algorithm parameters
        self.gamma = 0.99  # discount factor
        self.tau = 0.001  # for soft update of target parameters

    def preprocess_state(self, state):
        return state[2]    

    def postprocess_action(self, action):
        complete_action = np.zeros(self.task.action_space.shape)
        complete_action[2] = action
        return complete_action

    def write_stats(self, stats):
        """Write single episode stats to CSV file."""
        df_stats = pd.DataFrame([stats], columns=self.stats_columns)  # single-row dataframe
        df_stats.to_csv(self.stats_filename, mode='a', index=False,
            header=not os.path.isfile(self.stats_filename))  # write header first time only

    def reset_episode_vars(self):
        self.episode += 1
        self.last_state = None
        self.last_action = None
        self.total_reward = 0.0
        self.count = 0

    def step(self, state, reward, done):
        # Transform state vector
        #state = (state - self.task.observation_space.low) / self.state_range  # scale to [0.0, 1.0]
        state = self.preprocess_state(state)
        state = state.reshape(1, -1)  # convert to row vector

        # Choose an action
        action = self.act(state)
        
        # Save experience / reward
        if self.last_state is not None and self.last_action is not None:
            self.memory.add(self.last_state, self.last_action, reward, state, done)
            self.total_reward += reward
            self.count += 1

        # Learn, if at end of episode
        if len(self.memory) > self.batch_size:
            experiences = self.memory.sample(self.batch_size)
            self.learn(experiences)

        self.last_state = state
        self.last_action = action

        if done:
            self.write_stats([self.episode_num, self.total_reward])
            self.episode_num += 1

            # Save model weights at regular intervals
            if self.save_weights_every and self.episode % self.save_weights_every == 0:
                self.actor_local.model.save_weights(self.actor_filename)
                self.critic_local.model.save_weights(self.critic_filename)
                print("Model weights saved at episode", self.episode) #[debug]
                print("Reward for this episode: ", reward)
                print("Total reward at this episode: ", self.total_reward)
            self.reset_episode_vars()

        return self.postprocess_action(action)

    def act(self, state):
        """Returns actions for given state(s) as per current policy."""
        state = np.reshape(state, [-1, self.state_size])
        actions = self.actor_local.model.predict(state)
        return actions + self.noise.sample()  # add some noise for exploration

    def learn(self, experiences):
        """Update policy and value parameters using given batch of experience tuples."""
        # Convert experience tuples to separate arrays for each element (states, actions, rewards, etc.)
        states = np.vstack([e.state for e in experiences if e is not None])
        actions = np.array([e.action for e in experiences if e is not None]).astype(np.float32).reshape(-1, self.action_size)
        rewards = np.array([e.reward for e in experiences if e is not None]).astype(np.float32).reshape(-1, 1)
        dones = np.array([e.done for e in experiences if e is not None]).astype(np.uint8).reshape(-1, 1)
        next_states = np.vstack([e.next_state for e in experiences if e is not None])

        # Get predicted next-state actions and Q values from target models
        #     Q_targets_next = critic_target(next_state, actor_target(next_state))
        actions_next = self.actor_target.model.predict_on_batch(next_states)
        Q_targets_next = self.critic_target.model.predict_on_batch([next_states, actions_next])

        # Compute Q targets for current states and train critic model (local)
        Q_targets = rewards + self.gamma * Q_targets_next * (1 - dones)
        self.critic_local.model.train_on_batch(x=[states, actions], y=Q_targets)

        # Train actor model (local)
        action_gradients = np.reshape(self.critic_local.get_action_gradients([states, actions, 0]), (-1, self.action_size))
        self.actor_local.train_fn([states, action_gradients, 1])  # custom training function

        # Soft-update target models
        self.soft_update(self.critic_local.model, self.critic_target.model)
        self.soft_update(self.actor_local.model, self.actor_target.model)

    def soft_update(self, local_model, target_model):
        local_weights = np.array(local_model.get_weights())
        target_weights = np.array(target_model.get_weights())

        new_weights = self.tau * local_weights + (1 - self.tau) * target_weights
        target_model.set_weights(new_weights)

class ReplayBuffer:
    """Fixed-size circular buffer to store experience tuples."""

    def __init__(self, size=1000):
        """Initialize a ReplayBuffer object."""
        self.size = size  # maximum size of buffer
        self.memory = []  # internal memory (list)
        self.idx = 0  # current index into circular buffer

    def add(self, state, action, reward, next_state, done):
        """Add a new experience to memory."""
        e = Experience(state, action, reward, next_state, done)
        if len(self.memory) < self.size:
            self.memory.append(e)
        else:
            self.memory[self.idx] = e
            self.idx = (self.idx + 1) % self.size
    
    def sample(self, batch_size=64):
        """Randomly sample a batch of experiences from memory."""
        return random.sample(self.memory, k=batch_size)

    def __len__(self):
        """Return the current size of internal memory."""
        return len(self.memory)

class Critic:
    """Critic (Value) Model."""
  
    def __init__(self, state_size, action_size):
        """Initialize parameters and build model.

        Params
        ======
            state_size (int): Dimension of each state
            action_size (int): Dimension of each action
        """
        self.state_size = state_size
        self.action_size = action_size

        # Initialize any other variables here
        self.critic_learning_rate = 0.001
        self.build_model()

    def build_model(self):
        """Build a critic (value) network that maps (state, action) pairs -> Q-values."""
        # Define input layers
        states = layers.Input(shape=(self.state_size,), name='states')
        actions = layers.Input(shape=(self.action_size,), name='actions')

        # Add hidden layer(s) for state pathway
        net_states = layers.Dense(units=8, activation='relu')(states)
        net_states = layers.Dense(units=8, activation='relu')(net_states)

        # Add hidden layer(s) for action pathway
        net_actions = layers.Dense(units=8, activation='relu')(actions)
        net_actions = layers.Dense(units=8, activation='relu')(net_actions)

        # Try different layer sizes, activations, add batch normalization, regularizers, etc.

        # Combine state and action pathways
        net = layers.Add()([net_states, net_actions])
        net = layers.Activation('relu')(net)

        # Add more layers to the combined network if needed

        # Add final output layer to prduce action values (Q values)
        Q_values = layers.Dense(units=1, name='q_values')(net)

        # Create Keras model
        self.model = models.Model(inputs=[states, actions], outputs=Q_values)

        # Define optimizer and compile model for training with built-in loss function
        optimizer = optimizers.Adam(lr = self.critic_learning_rate)
        self.model.compile(optimizer=optimizer, loss='mse')
        self.model.summary()
        # Compute action gradients (derivative of Q values w.r.t. to actions)
        action_gradients = K.gradients(Q_values, actions)

        # Define an additional function to fetch action gradients (to be used by actor model)
        self.get_action_gradients = K.function(
            inputs=[*self.model.input, K.learning_phase()],
            outputs=action_gradients)

class Actor:
    """Actor (Policy) Model."""

    def __init__(self, state_size, action_size, action_low, action_high):
        """Initialize parameters and build model.

        Params
        ======
            state_size (int): Dimension of each state
            action_size (int): Dimension of each action
            action_low (array): Min value of each action dimension
            action_high (array): Max value of each action dimension
        """
        self.state_size = state_size
        self.action_size = action_size
        self.action_low = action_low
        self.action_high = action_high
        self.action_range = self.action_high - self.action_low
        self.actor_learning_rate = 0.00001

        # Initialize any other variables here

        self.build_model()

    def build_model(self):
        """Build an actor (policy) network that maps states -> actions."""
        # Define input layer (states)
        states = layers.Input(shape=(self.state_size,), name='states')

        # Add hidden layers
        net = layers.Dense(units=8, activation='relu')(states)
        net = layers.Dense(units=8, activation='relu')(net)
        net = layers.Dense(units=8, activation='relu')(net)

        # Try different layer sizes, activations, add batch normalization, regularizers, etc.

        # Add final output layer with sigmoid activation
        raw_actions = layers.Dense(units=self.action_size, activation='sigmoid',
            name='raw_actions')(net)

        # Scale [0, 1] output for each action dimension to proper range
        actions = layers.Lambda(lambda x: (x * self.action_range) + self.action_low,
            name='actions')(raw_actions)

        # Create Keras model
        self.model = models.Model(inputs=states, outputs=actions)
        self.model.summary()
        # Define loss function using action value (Q value) gradients
        action_gradients = layers.Input(shape=(self.action_size,))
        loss = K.mean(-action_gradients * actions)

        # Incorporate any additional losses here (e.g. from regularizers)

        # Define optimizer and training function
        optimizer = optimizers.Adam(lr = self.actor_learning_rate)
        updates_op = optimizer.get_updates(params=self.model.trainable_weights, loss=loss)
        self.train_fn = K.function(
            inputs=[self.model.input, action_gradients, K.learning_phase()],
            outputs=[],
            updates=updates_op)

class OUNoise:
    """Ornstein-Uhlenbeck process."""

    def __init__(self, size, mu=None, theta=0.15, sigma=0.3):
        """Initialize parameters and noise process."""
        self.size = size
        self.mu = mu if mu is not None else np.zeros(self.size)
        self.theta = theta
        self.sigma = sigma
        self.state = np.ones(self.size) * self.mu
        self.reset()

    def reset(self):
        """Reset the internal state (= noise) to mean (mu)."""
        self.state = self.mu

    def sample(self):
        """Update internal state and return it as a noise sample."""
        x = self.state
        dx = self.theta * (self.mu - x) + self.sigma * np.random.randn(len(x))
        self.state = x + dx
        return self.state
