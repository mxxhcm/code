import tensorflow as tf
from experimental.LSTM_MADDPG_TF2.model.trainer.maddpg_actor import MADDPGAgentTrainer as MADDPG_ACTOR
from experimental.LSTM_MADDPG_TF2.model.trainer.maddpg_critic import MADDPGAgentTrainer as MADDPG_CRITIC
import tensorflow.nn.rnn_cell as rnn
import tensorflow.contrib.layers as layers


# lstm模型
# inputs: list of [batch_size, dim, time_step]
def lstm_model(inputs, history_length, batch_size, reuse=False, layers_number=2, scope="l", rnn_cell=None):
    shape = inputs[0].shape
    lstm_size = shape[1]
    observation_n = []
    for i in range(len(inputs)):
        obs = inputs[i]
        if not reuse:
            if i == 0:
                reuse = False
            else:
                reuse = True
        with tf.variable_scope(scope, reuse=reuse):
            x = obs
            x = tf.transpose(x, (2, 0, 1))  # (time_steps, batch_size,state_size)
            lstm_cell = rnn.BasicLSTMCell(lstm_size, forget_bias=1, state_is_tuple=True)
            cell = rnn.MultiRNNCell([lstm_cell] * layers_number, state_is_tuple=True)
            with tf.variable_scope("Multi_Layer_RNN"):
                cell_outputs, states = tf.nn.dynamic_rnn(cell, x, dtype=tf.float32)
            outputs = cell_outputs[-1:, :, :]
            outputs = tf.squeeze(outputs, 0)
            observation_n.append(outputs)
    return observation_n


def q_model(inputs, num_outputs, scope, reuse=False,  num_units=64):

    # This model takes as input an observation and returns values of all actions
    with tf.variable_scope(scope, reuse=reuse):
        out = inputs
        out = layers.fully_connected(out, num_outputs=num_units, activation_fn=tf.nn.relu)
        out = layers.fully_connected(out, num_outputs=num_units, activation_fn=tf.nn.relu)
        out = layers.fully_connected(out, num_outputs=num_outputs, activation_fn=None)
        return out


# multi perception layers
def mlp_model(input, num_outputs, scope, reuse=False, num_units=64, rnn_cell=None):
    # This model takes as input an observation and returns values of all actions
    with tf.variable_scope(scope, reuse=reuse):
        out = input
        out = layers.fully_connected(out, num_outputs=num_units, activation_fn=tf.nn.relu)
        out = layers.fully_connected(out, num_outputs=num_units, activation_fn=tf.nn.relu)
        out = layers.fully_connected(out, num_outputs=num_outputs, activation_fn=None)
        return out


def make_env(scenario_name, arglist, benchmark=False):
    from experimental.LSTM_MADDPG_TF2.multiagent.environment_uav import MultiAgentEnv
    import experimental.LSTM_MADDPG_TF2.multiagent.scenarios as scenarios

    # load scenario from script
    scenario = scenarios.load(scenario_name + ".py").Scenario()
    # create world
    world = scenario.make_world()
    # create multiagent environment
    if benchmark:
        env = MultiAgentEnv(world, scenario.reset_world, scenario.reward, scenario.observation, scenario.benchmark_data)
    else:
        env = MultiAgentEnv(world, scenario.reset_world, scenario.reward, scenario.observation)
    return env


def get_trainers(env, env_name, num_adversaries, obs_shape_n, arglist, is_actor=True, acotr=None):
    trainers = []
    model = mlp_model
    lstm = lstm_model
    if is_actor:
        trainer = MADDPG_ACTOR
        for i in range(num_adversaries):
            trainers.append(trainer(
                env_name + "agent_%d" % i, model, lstm, obs_shape_n, env.action_space, i, arglist,
                local_q_func=(arglist.adv_policy == 'ddpg')))
        for i in range(num_adversaries, env.n):
            trainers.append(trainer(
                env_name + "agent_%d" % i, model, lstm, obs_shape_n, env.action_space, i, arglist,
                local_q_func=(arglist.good_policy == 'ddpg')))

    else:
        trainer = MADDPG_CRITIC
        for i in range(num_adversaries):
            trainers.append(trainer(
                env_name + "agent_%d" % i, model, lstm, obs_shape_n, env.action_space, i, acotr, arglist,
                local_q_func=(arglist.adv_policy == 'ddpg')))
        for i in range(num_adversaries, env.n):
            trainers.append(trainer(
                env_name + "agent_%d" % i, model, lstm, obs_shape_n, env.action_space, i, acotr, arglist,
                local_q_func=(arglist.good_policy == 'ddpg')))

    return trainers


def clipped_error(x):
  # Huber loss
  try:
    return tf.select(tf.abs(x) < 1.0, 0.5 * tf.square(x), tf.abs(x) - 0.5)
  except:
    return tf.where(tf.abs(x) < 1.0, 0.5 * tf.square(x), tf.abs(x) - 0.5)







