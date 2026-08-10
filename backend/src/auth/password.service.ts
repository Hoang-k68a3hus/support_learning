import { Injectable, type OnModuleInit } from '@nestjs/common';
import { randomBytes } from 'node:crypto';
import * as argon2 from 'argon2';

@Injectable()
export class PasswordService implements OnModuleInit {
  private dummyHash: string | null = null;

  async onModuleInit(): Promise<void> {
    this.dummyHash = await this.hash(randomBytes(32).toString('hex'));
  }

  hash(password: string): Promise<string> {
    return argon2.hash(password, { type: argon2.argon2id });
  }

  verify(hash: string, password: string): Promise<boolean> {
    return argon2.verify(hash, password);
  }

  async verifyForAuthentication(hash: string | null, password: string): Promise<boolean> {
    if (!this.dummyHash) {
      throw new Error('PasswordService authentication verifier is not initialized');
    }

    const valid = await this.verify(hash ?? this.dummyHash, password);
    return hash !== null && valid;
  }
}
